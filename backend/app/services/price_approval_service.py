"""Manager approval requests when selling price is below catalog minimum."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.price_approval import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    PriceApproval,
)
from app.services.estimate_price_gate import PriceGateResult, ProductLine

logger = logging.getLogger(__name__)


class PriceApprovalPending(Exception):
    """Raised when payment is held for manager approval instead of blocked hard."""

    def __init__(self, message: str, *, approval_url: str, approval_id: int):
        super().__init__(message)
        self.approval_url = approval_url
        self.approval_id = approval_id


def _user_display_name(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    parts = [user.get("NAME"), user.get("LAST_NAME")]
    name = " ".join(str(p) for p in parts if p).strip()
    return name or None


def _lines_payload(lines: list[ProductLine]) -> dict[str, Any]:
    payload_lines: list[dict[str, Any]] = []
    below_count = 0
    for line in lines:
        below = line.is_below_minimum
        if below:
            below_count += 1
        discount = None
        if line.catalog_min_price is not None and below:
            discount = str(
                (line.catalog_min_price - line.compare_unit_price).quantize(Decimal("0.01"))
            )
        payload_lines.append(
            {
                "product_id": line.product_id,
                "product_name": line.product_name,
                "quantity": str(line.quantity),
                "selling_price": str(line.compare_unit_price),
                "selling_price_ex_vat": str(line.selling_price),
                "catalog_min_price": (
                    str(line.catalog_min_price) if line.catalog_min_price is not None else None
                ),
                "tax_rate": str(line.tax_rate),
                "tax_included": line.tax_included,
                "line_total": str(line.line_total),
                "below_minimum": below,
                "discount_amount": discount,
                "status": (
                    "BELOW MIN"
                    if below and line.catalog_min_price is not None
                    else ("NO CATALOG" if line.catalog_min_price is None else "OK")
                ),
            }
        )
    return {
        "lines": payload_lines,
        "below_minimum_count": below_count,
        "ok_count": len(payload_lines) - below_count,
        "product_count": len(payload_lines),
    }


class PriceApprovalService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.bitrix = get_bitrix_client(self.settings)

    def build_approval_url(self, token: str) -> str:
        base = self.settings.payment_frontend_base_url or self.settings.public_base_url
        return f"{base.rstrip('/')}/approvals/{token}"

    def get_by_token(self, token: str) -> PriceApproval | None:
        return self.db.scalar(
            select(PriceApproval)
            .options(selectinload(PriceApproval.workflow))
            .where(PriceApproval.token == token)
        )

    def get_pending_for_lead(self, lead_id: int) -> PriceApproval | None:
        return self.db.scalar(
            select(PriceApproval)
            .where(
                PriceApproval.bitrix_lead_id == lead_id,
                PriceApproval.status == STATUS_PENDING,
            )
            .order_by(PriceApproval.created_at.desc())
        )

    def to_public_dict(self, approval: PriceApproval) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires = approval.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        expired = approval.status == STATUS_PENDING and expires <= now
        payload = approval.lines_payload or {}
        lines = payload.get("lines") or []
        below_lines = [line for line in lines if line.get("below_minimum")]
        ok_lines = [line for line in lines if not line.get("below_minimum")]
        installment = payload.get("installment_policy") or {}

        # Re-read installment fields from the stored lead so money/enum fixes apply
        # to pending approvals created before the field-mapping correction.
        if approval.status == STATUS_PENDING and not expired:
            lead = {}
            workflow = getattr(approval, "workflow", None)
            if workflow is not None:
                lead = workflow.bitrix_lead_payload or {}
            if lead:
                from decimal import Decimal

                from app.services.installment_plan import (
                    evaluate_installment_policy,
                    installment_policy_payload,
                )

                refreshed = installment_policy_payload(
                    evaluate_installment_policy(
                        lead,
                        self.settings,
                        payable_total=Decimal(str(approval.total_payable or "0")),
                    )
                )
                if refreshed.get("needs_approval") or installment.get("needs_approval"):
                    installment = refreshed
                    payload = dict(payload)
                    payload["installment_policy"] = refreshed
                    kinds = list(payload.get("approval_kinds") or [])
                    if refreshed.get("needs_approval") and "installment" not in kinds:
                        kinds.append("installment")
                    payload["approval_kinds"] = kinds
                    approval.lines_payload = payload

        issues = installment.get("issues") or {}
        kinds = payload.get("approval_kinds") or (
            ["price"] if below_lines else []
        )
        if installment.get("needs_approval") and "installment" not in kinds:
            kinds = [*kinds, "installment"]
        return {
            "id": approval.id,
            "token": approval.token,
            "status": "expired" if expired else approval.status,
            "lead_id": approval.bitrix_lead_id,
            "lead_title": approval.lead_title,
            "currency": approval.currency,
            "total_payable": approval.total_payable,
            "catalog_minimum_total": approval.catalog_minimum_total,
            "reason": approval.reason,
            "lines": lines,
            "below_minimum_lines": below_lines,
            "ok_lines": ok_lines,
            "product_count": payload.get("product_count", len(lines)),
            "below_minimum_count": payload.get("below_minimum_count", len(below_lines)),
            "ok_count": payload.get("ok_count", len(ok_lines)),
            "approval_kinds": kinds,
            "installment_policy": installment,
            "cases": self._case_cards(below_lines=below_lines, installment=installment),
            "editable": {
                "price": bool(below_lines),
                "first_installment_amount": bool(issues.get("first_below_percent")),
                "installment_dates": bool(issues.get("gap_over_limit")),
                "installment_amounts": bool(issues.get("missing_amounts")),
                "count_note": bool(issues.get("count_above_two")),
            },
            "required_percent": str(self.settings.payment_required_percent),
            "owner_name": approval.owner_name,
            "manager_email": approval.manager_email,
            "manager_name": approval.manager_name,
            "notified_via": approval.notified_via,
            "notified_at": approval.notified_at.isoformat() if approval.notified_at else None,
            "decision_note": approval.decision_note,
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
            "approval_url": self.build_approval_url(approval.token),
        }

    @staticmethod
    def _case_cards(
        *,
        below_lines: list[dict],
        installment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """One card per policy issue so the manager can approve/reject each case."""
        issues = installment.get("issues") or {}
        reasons = installment.get("reasons") or []
        cards: list[dict[str, Any]] = []
        if below_lines:
            cards.append(
                {
                    "id": "price",
                    "title": "Course prices below minimum",
                    "summary": "One or more courses are priced under catalog minimum.",
                    "reject_fields": "preferred_prices",
                }
            )
        if issues.get("first_below_percent"):
            cards.append(
                {
                    "id": "first_below",
                    "title": "Installment 1 below minimum %",
                    "summary": next((r for r in reasons if "below the" in r), reasons[0] if reasons else ""),
                    "reject_fields": "preferred_first_amount",
                }
            )
        if issues.get("count_above_two"):
            cards.append(
                {
                    "id": "count",
                    "title": "Installment count above 2",
                    "summary": next((r for r in reasons if "more than 2" in r), "Count is more than 2."),
                    "reject_fields": None,
                }
            )
        if issues.get("gap_over_limit"):
            cards.append(
                {
                    "id": "gap",
                    "title": "Due date gap over 30 days",
                    "summary": next((r for r in reasons if "days after" in r), "Installment 2 due date is too far."),
                    "reject_fields": "preferred_dates",
                }
            )
        if issues.get("missing_amounts"):
            cards.append(
                {
                    "id": "missing_amounts",
                    "title": "Missing installment amounts",
                    "summary": next(
                        (r for r in reasons if "no amount" in r.lower()),
                        "One or more installments have a due date but no amount.",
                    ),
                    "reject_fields": "preferred_amounts",
                }
            )
        return cards

    async def request_manager_approval(
        self,
        workflow: CustomerWorkflow,
        gate: PriceGateResult | None,
        *,
        lead: dict[str, Any],
        installment_policy: dict[str, Any] | None = None,
    ) -> PriceApproval:
        """Create/reuse a pending approval and email the owner's manager."""
        existing = self.get_pending_for_lead(workflow.bitrix_lead_id)
        if existing:
            expires = existing.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > datetime.now(timezone.utc):
                # Enrich an existing pending request with installment details if missing.
                if installment_policy and installment_policy.get("needs_approval"):
                    payload = dict(existing.lines_payload or {})
                    if not payload.get("installment_policy"):
                        payload["installment_policy"] = installment_policy
                        kinds = list(payload.get("approval_kinds") or [])
                        if "installment" not in kinds:
                            kinds.append("installment")
                        payload["approval_kinds"] = kinds
                        reasons = [existing.reason] if existing.reason else []
                        for reason in installment_policy.get("reasons") or []:
                            if reason not in reasons:
                                reasons.append(reason)
                        existing.reason = "\n".join(reasons)
                        existing.lines_payload = payload
                        self.db.commit()
                        self.db.refresh(existing)
                logger.info(
                    "Reusing pending price approval %s for lead %s | notified=%s",
                    existing.id,
                    workflow.bitrix_lead_id,
                    existing.notified_via or "no",
                )
                if not existing.notified_at:
                    await self._deliver(existing)
                elif "sendgrid" not in (existing.notified_via or "").split("+"):
                    await self._retry_existing_via_sendgrid(existing)
                return existing

        owner_id_raw = lead.get("ASSIGNED_BY_ID") or lead.get("assignedById")
        try:
            owner_id = int(owner_id_raw) if owner_id_raw not in (None, "", "0") else None
        except (TypeError, ValueError):
            owner_id = None

        owner = await self.bitrix.get_user(owner_id) if owner_id else None
        manager = await self.bitrix.resolve_manager_for_user(owner_id) if owner_id else None

        manager_email = (manager or {}).get("EMAIL") if manager else None
        manager_user_id = None
        if manager:
            try:
                manager_user_id = int(manager.get("ID") or manager.get("id") or 0) or None
            except (TypeError, ValueError):
                manager_user_id = None

        if not manager_email and self.settings.bitrix_approval_fallback_email:
            manager_email = self.settings.bitrix_approval_fallback_email.strip()
            logger.warning(
                "No Bitrix manager for owner %s - using fallback %s",
                owner_id,
                manager_email,
            )

        kinds: list[str] = []
        if gate is not None and not gate.ok:
            kinds.append("price")
        if installment_policy and installment_policy.get("needs_approval"):
            kinds.append("installment")

        if not manager_email:
            raise ValueError(
                "Manager approval is required, but no manager email was found "
                "for the lead owner. Set the owner's department manager in Bitrix, or set "
                "BITRIX_APPROVAL_FALLBACK_EMAIL."
            )

        reasons: list[str] = []
        if gate is not None and gate.reason:
            reasons.append(gate.reason)
        for reason in (installment_policy or {}).get("reasons") or []:
            if reason not in reasons:
                reasons.append(reason)

        total_payable = (
            f"{gate.total_payable:.2f}"
            if gate is not None and gate.total_payable > 0
            else f"{Decimal(workflow.total_amount or 0):.2f}"
        )
        catalog_min = (
            f"{gate.catalog_minimum_total:.2f}"
            if gate is not None
            else f"{Decimal(workflow.total_amount or 0):.2f}"
        )
        lines_payload = _lines_payload(gate.lines) if gate is not None else {
            "lines": [],
            "below_minimum_count": 0,
            "ok_count": 0,
            "product_count": 0,
        }
        lines_payload["approval_kinds"] = kinds
        if installment_policy:
            lines_payload["installment_policy"] = installment_policy

        token = secrets.token_urlsafe(32)
        approval = PriceApproval(
            workflow_id=workflow.id,
            bitrix_lead_id=workflow.bitrix_lead_id,
            token=token,
            status=STATUS_PENDING,
            currency=workflow.currency or self.settings.default_currency,
            total_payable=total_payable,
            catalog_minimum_total=catalog_min,
            reason="\n".join(reasons),
            lines_payload=lines_payload,
            lead_title=str(lead.get("TITLE") or lead.get("title") or f"Lead {workflow.bitrix_lead_id}"),
            owner_user_id=owner_id,
            owner_name=_user_display_name(owner),
            manager_user_id=manager_user_id,
            manager_email=manager_email,
            manager_name=_user_display_name(manager),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=self.settings.price_approval_ttl_hours),
        )
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)

        approval_url = self.build_approval_url(token)
        channels = await self._deliver(approval)

        delivery = (
            f"Notified via: {', '.join(channels)}."
            if channels
            else (
                "Could not email or notify the manager automatically "
                "(Bitrix mail/chat not available to this webhook) - "
                "share the link below with them."
            )
        )
        summary = ""
        if gate is not None:
            summary = gate.summary_comment(
                currency=approval.currency, amount_paid=workflow.amount_paid
            ) + "\n\n"
        installment_block = ""
        if installment_policy and installment_policy.get("reasons"):
            installment_block = (
                "Installment policy:\n"
                + "\n".join(f"- {r}" for r in installment_policy["reasons"])
                + "\n\n"
            )
        try:
            await self.bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=workflow.bitrix_lead_id,
                comment=(
                    f"{summary}{installment_block}"
                    f"Pending manager approval - {manager_email}.\n"
                    f"{delivery}\n"
                    f"Approval link: {approval_url}"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to post approval-pending comment on lead %s", workflow.bitrix_lead_id
            )

        return approval

    async def _deliver(self, approval: PriceApproval) -> list[str]:
        """Send the approval to the manager and remember whether it got through."""
        approval_url = self.build_approval_url(approval.token)
        channels = await self._notify_manager(approval, approval_url)

        if channels:
            approval.notified_at = datetime.now(timezone.utc)
            approval.notified_via = "+".join(channels)[:50]
            self.db.commit()
            self.db.refresh(approval)
            logger.info(
                "OK approval sent | lead_id=%s approval_id=%s manager=%s via=%s url=%s",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_email,
                approval.notified_via,
                approval_url,
            )
        else:
            logger.warning(
                "Approval not delivered | lead_id=%s approval_id=%s manager=%s "
                "reason=no_working_channel action=set_SENDGRID_API_KEY_or_enable_im_scope "
                "retry=next_stage_trigger url=%s",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_email,
                approval_url,
            )
        return channels

    async def _retry_existing_via_sendgrid(self, approval: PriceApproval) -> bool:
        """Upgrade an old chat-only approval to SendGrid without repeating chat."""
        previous = [
            channel
            for channel in (approval.notified_via or "").split("+")
            if channel
        ]
        logger.info(
            "RETRY existing approval via SendGrid | lead_id=%s approval_id=%s "
            "previous_via=%s to=%s reason=sendgrid_not_previously_delivered",
            approval.bitrix_lead_id,
            approval.id,
            approval.notified_via or "none",
            approval.manager_email or "-",
        )
        if not await self._try_sendgrid(approval):
            logger.warning(
                "RETRY SendGrid not delivered | lead_id=%s approval_id=%s "
                "previous_via=%s action=check_SendGrid_logs_and_configuration",
                approval.bitrix_lead_id,
                approval.id,
                approval.notified_via or "none",
            )
            return False

        channels = list(dict.fromkeys([*previous, "sendgrid"]))
        approval.notified_at = datetime.now(timezone.utc)
        approval.notified_via = "+".join(channels)[:50]
        self.db.commit()
        self.db.refresh(approval)
        logger.info(
            "OK existing approval upgraded to SendGrid | lead_id=%s approval_id=%s "
            "via=%s to=%s",
            approval.bitrix_lead_id,
            approval.id,
            approval.notified_via,
            approval.manager_email,
        )
        return True

    async def _try_sendgrid(self, approval: PriceApproval) -> bool:
        """Attempt one approval email and log enough detail to diagnose delivery."""
        if not approval.manager_email:
            logger.warning(
                "SKIP SendGrid | lead_id=%s approval_id=%s reason=no_manager_email "
                "action=set_department_manager_or_BITRIX_APPROVAL_FALLBACK_EMAIL",
                approval.bitrix_lead_id,
                approval.id,
            )
            return False
        if not self.settings.use_mock_integrations and not self.settings.sendgrid_api_key:
            logger.error(
                "SKIP SendGrid | lead_id=%s approval_id=%s to=%s "
                "reason=SENDGRID_API_KEY_missing action=set_Railway_SENDGRID_API_KEY",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_email,
            )
            return False

        subject = f"Approval needed - {approval.lead_title}"
        body = self._email_body(approval, self.build_approval_url(approval.token))
        logger.info(
            "TRY approval delivery | channel=sendgrid lead_id=%s approval_id=%s "
            "to=%s from=%s subject=%s",
            approval.bitrix_lead_id,
            approval.id,
            approval.manager_email,
            self.settings.sendgrid_from_email,
            subject,
        )
        try:
            sent = get_email_client(self.settings).send_price_approval(
                to_email=approval.manager_email,
                manager_name=approval.manager_name,
                subject=subject,
                body=body,
            )
        except Exception:
            logger.exception(
                "FAIL approval delivery | channel=sendgrid lead_id=%s approval_id=%s "
                "to=%s action=check_SendGrid_activity",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_email,
            )
            return False
        if sent:
            logger.info(
                "OK approval delivery | channel=sendgrid lead_id=%s approval_id=%s to=%s",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_email,
            )
            return True
        logger.error(
            "FAIL approval delivery | channel=sendgrid lead_id=%s approval_id=%s "
            "to=%s action=check_previous_SendGrid_log",
            approval.bitrix_lead_id,
            approval.id,
            approval.manager_email,
        )
        return False

    async def _notify_manager(self, approval: PriceApproval, approval_url: str) -> list[str]:
        """Prefer SendGrid, then Bitrix chat. Bitrix mail is skipped (portal often lacks it)."""
        subject = f"Approval needed - {approval.lead_title}"
        body = self._email_body(approval, approval_url)
        delivered: list[str] = []
        attempts: list[str] = []

        if await self._try_sendgrid(approval):
            delivered.append("sendgrid")
            attempts.append("sendgrid=ok")
        else:
            attempts.append("sendgrid=failed")

        if not delivered and approval.manager_user_id:
            logger.info(
                "TRY approval delivery | channel=bitrix_chat lead_id=%s approval_id=%s user_id=%s "
                "reason=sendgrid_unavailable",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_user_id,
            )
            try:
                if await self.bitrix.notify_user(
                    user_id=approval.manager_user_id,
                    message=f"{subject}\n{approval_url}",
                ):
                    delivered.append("bitrix_chat")
                    attempts.append("bitrix_chat=ok")
                else:
                    attempts.append("bitrix_chat=failed")
            except Exception:
                attempts.append("bitrix_chat=exception")
                logger.exception(
                    "Bitrix approval notification raised | approval_id=%s", approval.id
                )
        elif not delivered:
            attempts.append("bitrix_chat=skipped_no_manager_user_id")
            logger.warning(
                "SKIP Bitrix chat | lead_id=%s approval_id=%s reason=no_manager_user_id "
                "fix=resolve_department_manager_or_add_im_scope",
                approval.bitrix_lead_id,
                approval.id,
            )

        logger.info(
            "Approval delivery result | lead_id=%s approval_id=%s manager=%s "
            "via=%s attempts=%s url=%s",
            approval.bitrix_lead_id,
            approval.id,
            approval.manager_email or "-",
            "+".join(delivered) if delivered else "none",
            ",".join(attempts),
            approval_url,
        )
        return delivered

    def _email_body(self, approval: PriceApproval, approval_url: str) -> str:
        payload = approval.lines_payload or {}
        all_lines = payload.get("lines") or []
        below = [line for line in all_lines if line.get("below_minimum")]
        ok = [line for line in all_lines if not line.get("below_minimum")]
        below_count = payload.get("below_minimum_count", len(below))
        product_count = payload.get("product_count", len(all_lines))
        installment = payload.get("installment_policy") or {}
        kinds = payload.get("approval_kinds") or []

        lines = [
            f"Hello {approval.manager_name or 'Manager'},",
            "",
            "A payment link needs your approval before it can be sent.",
            "",
            f"Lead: {approval.lead_title} (#{approval.bitrix_lead_id})",
            f"Owner: {approval.owner_name or approval.owner_user_id or '-'}",
            f"Proposed total: {approval.total_payable} {approval.currency}",
        ]
        if "price" in kinds or below:
            lines.extend(
                [
                    f"Catalog minimum total: {approval.catalog_minimum_total} {approval.currency}",
                    f"Products: {product_count} total | {below_count} below minimum",
                    "",
                    f"Needs price approval ({below_count}):",
                ]
            )
            if below:
                for line in below:
                    catalog = line.get("catalog_min_price") or "missing"
                    discount = line.get("discount_amount")
                    discount_txt = f" | discount {discount}" if discount else ""
                    lines.append(
                        f"- {line.get('product_name')} × {line.get('quantity')} | "
                        f"selling {line.get('selling_price')} | catalog min {catalog}"
                        f"{discount_txt} | BELOW MIN"
                    )
            else:
                lines.append("- (none)")
            lines.append("")
            lines.append(f"At / above minimum ({len(ok)}):")
            if ok:
                for line in ok:
                    catalog = line.get("catalog_min_price") or "missing"
                    lines.append(
                        f"- {line.get('product_name')} × {line.get('quantity')} | "
                        f"selling {line.get('selling_price')} | catalog min {catalog} | OK"
                    )
            else:
                lines.append("- (none)")

        if installment.get("needs_approval"):
            lines.extend(["", "Installment policy:"])
            for reason in installment.get("reasons") or []:
                lines.append(f"- {reason}")
            schedule = installment.get("schedule") or []
            if schedule:
                lines.append("Schedule:")
                for slot in schedule:
                    lines.append(
                        f"- Installment {slot.get('number')}: "
                        f"{slot.get('amount') or '-'} due {slot.get('due_date') or '-'}"
                    )

        lines.extend(
            [
                "",
                f"Open approval page: {approval_url}",
                "",
                "If you APPROVE, the payment link is sent.",
                "If you REJECT, no payment link is sent.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _clean_suggested_prices(rows: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        for row in rows:
            try:
                product_id = int(row.get("product_id") or 0)
            except (TypeError, ValueError):
                continue
            if product_id <= 0:
                continue
            price = row.get("selling_price")
            if price is None or str(price).strip() == "":
                continue
            cleaned.append({"product_id": product_id, "selling_price": str(price)})
        return cleaned

    @staticmethod
    def _clean_suggested_dates(rows: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        for row in rows:
            try:
                number = int(row.get("number") or 0)
            except (TypeError, ValueError):
                continue
            due = str(row.get("due_date") or "").strip()
            if number <= 0 or not due:
                continue
            cleaned.append({"number": number, "due_date": due})
        return cleaned

    @staticmethod
    def _clean_suggested_amounts(rows: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        for row in rows:
            try:
                number = int(row.get("number") or 0)
            except (TypeError, ValueError):
                continue
            amount = row.get("amount")
            if number <= 0 or amount is None or str(amount).strip() == "":
                continue
            cleaned.append({"number": number, "amount": str(amount)})
        return cleaned

    @staticmethod
    def _rejection_preferred_block(approval: PriceApproval) -> str:
        payload = approval.lines_payload or {}
        currency = approval.currency or "AED"
        parts: list[str] = []
        lines_by_id = {
            int(row.get("product_id") or 0): row
            for row in (payload.get("lines") or [])
            if int(row.get("product_id") or 0) > 0
        }
        for row in payload.get("manager_suggested_prices") or []:
            pid = int(row.get("product_id") or 0)
            meta = lines_by_id.get(pid) or {}
            name = str(meta.get("product_name") or f"Product {pid}")
            parts.append(
                f"  • {name}: preferred {row.get('selling_price')} {currency}"
                + (
                    f" (was {meta.get('selling_price')})"
                    if meta.get("selling_price") is not None
                    else ""
                )
            )
        for row in payload.get("manager_suggested_dates") or []:
            parts.append(
                f"  • Installment {row.get('number')}: preferred due date {row.get('due_date')}"
            )
        for row in payload.get("manager_suggested_amounts") or []:
            parts.append(
                f"  • Installment {row.get('number')}: preferred amount "
                f"{row.get('amount')} {currency}"
            )
        if not parts:
            return ""
        return "Manager preferred values:\n" + "\n".join(parts) + "\n"

    async def decide(
        self,
        token: str,
        *,
        approve: bool,
        note: str | None = None,
        suggested_prices: list[dict] | None = None,
        suggested_dates: list[dict] | None = None,
        suggested_amounts: list[dict] | None = None,
        rejected_case: str | None = None,
    ) -> PriceApproval:
        approval = self.get_by_token(token)
        if not approval:
            raise ValueError("This approval link is invalid.")
        if approval.status != STATUS_PENDING:
            raise ValueError(f"This request was already {approval.status}.")

        expires = approval.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise ValueError("This approval link has expired.")

        approval.status = STATUS_APPROVED if approve else STATUS_REJECTED
        approval.decided_at = datetime.now(timezone.utc)
        approval.decision_note = (note or "").strip() or None
        if not approve:
            payload = dict(approval.lines_payload or {})
            if rejected_case:
                payload["rejected_case"] = rejected_case
            cleaned_prices = self._clean_suggested_prices(suggested_prices or [])
            if cleaned_prices:
                payload["manager_suggested_prices"] = cleaned_prices
            cleaned_dates = self._clean_suggested_dates(suggested_dates or [])
            if cleaned_dates:
                payload["manager_suggested_dates"] = cleaned_dates
            cleaned_amounts = self._clean_suggested_amounts(suggested_amounts or [])
            if cleaned_amounts:
                payload["manager_suggested_amounts"] = cleaned_amounts
            approval.lines_payload = payload
        self.db.commit()
        self.db.refresh(approval)

        kinds = (approval.lines_payload or {}).get("approval_kinds") or ["price"]
        label = " / ".join(kinds) if kinds else "request"
        if approve:
            comment = (
                f"APPROVED by manager ({approval.manager_email or 'unknown'}) - {label}.\n"
                f"Proposed total {approval.total_payable} {approval.currency}.\n"
                "Payment link will be generated."
            )
        else:
            owner = approval.owner_name or (
                f"user #{approval.owner_user_id}" if approval.owner_user_id else "lead owner"
            )
            preferred_block = self._rejection_preferred_block(approval)
            case_label = (approval.lines_payload or {}).get("rejected_case") or label
            comment = (
                f"REJECTED by manager ({approval.manager_email or 'unknown'}) - {case_label}.\n"
                f"Responsible person: {owner}\n"
                f"Reason note: {approval.decision_note or '-'}\n"
                f"{preferred_block}"
                "No payment link was sent. Please update the lead (price / installment plan) "
                "and move it to the payment stage again if needed."
            )
        try:
            await self.bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=approval.bitrix_lead_id,
                comment=comment,
            )
        except Exception:
            logger.exception(
                "Failed to post approval decision comment on lead %s",
                approval.bitrix_lead_id,
            )
        return approval
