"""Manager approval requests when selling price is below catalog minimum."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    return {
        "lines": [
            {
                "product_id": line.product_id,
                "product_name": line.product_name,
                "quantity": str(line.quantity),
                "selling_price": str(line.selling_price),
                "catalog_min_price": (
                    str(line.catalog_min_price) if line.catalog_min_price is not None else None
                ),
                "tax_rate": str(line.tax_rate),
                "tax_included": line.tax_included,
                "line_total": str(line.line_total),
                "below_minimum": line.is_below_minimum,
            }
            for line in lines
        ]
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
        return self.db.scalar(select(PriceApproval).where(PriceApproval.token == token))

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
            "lines": (approval.lines_payload or {}).get("lines") or [],
            "owner_name": approval.owner_name,
            "manager_email": approval.manager_email,
            "manager_name": approval.manager_name,
            "notified_via": approval.notified_via,
            "notified_at": approval.notified_at.isoformat() if approval.notified_at else None,
            "decision_note": approval.decision_note,
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
            "approval_url": self.build_approval_url(approval.token),
        }

    async def request_manager_approval(
        self,
        workflow: CustomerWorkflow,
        gate: PriceGateResult,
        *,
        lead: dict[str, Any],
    ) -> PriceApproval:
        """Create/reuse a pending approval and email the owner's manager via Bitrix mail."""
        existing = self.get_pending_for_lead(workflow.bitrix_lead_id)
        if existing:
            expires = existing.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > datetime.now(timezone.utc):
                logger.info(
                    "Reusing pending price approval %s for lead %s | notified=%s",
                    existing.id,
                    workflow.bitrix_lead_id,
                    existing.notified_via or "no",
                )
                # An earlier send may have failed (missing Bitrix scope, no mailbox).
                # Retry until the manager has actually been reached at least once.
                if not existing.notified_at:
                    await self._deliver(existing)
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
                "No Bitrix manager for owner %s — using fallback %s",
                owner_id,
                manager_email,
            )

        if not manager_email:
            raise ValueError(
                "Selling price is below catalog minimum, but no manager email was found "
                "for the lead owner. Set the owner's department manager in Bitrix, or set "
                "BITRIX_APPROVAL_FALLBACK_EMAIL."
            )

        token = secrets.token_urlsafe(32)
        approval = PriceApproval(
            workflow_id=workflow.id,
            bitrix_lead_id=workflow.bitrix_lead_id,
            token=token,
            status=STATUS_PENDING,
            currency=workflow.currency or self.settings.default_currency,
            total_payable=f"{gate.total_payable:.2f}",
            catalog_minimum_total=f"{gate.catalog_minimum_total:.2f}",
            reason=gate.reason,
            lines_payload=_lines_payload(gate.lines),
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

        # The timeline comment is the channel that always works with the crm scope,
        # so the link reaches Bitrix even when mail and chat are unavailable.
        delivery = (
            f"Notified via: {', '.join(channels)}."
            if channels
            else (
                "Could not email or notify the manager automatically "
                "(Bitrix mail/chat not available to this webhook) — "
                "share the link below with them."
            )
        )
        try:
            await self.bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=workflow.bitrix_lead_id,
                comment=(
                    f"{gate.summary_comment(currency=approval.currency, amount_paid=workflow.amount_paid)}\n\n"
                    f"Pending manager approval — {manager_email}.\n"
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
                "reason=no_working_channel action=enable_mail_or_im_scope "
                "retry=next_stage_trigger url=%s",
                approval.bitrix_lead_id,
                approval.id,
                approval.manager_email,
                approval_url,
            )
        return channels

    async def _notify_manager(self, approval: PriceApproval, approval_url: str) -> list[str]:
        """Try Bitrix mail, then Bitrix chat, then the configured email client."""
        subject = f"Discount approval needed — {approval.lead_title}"
        body = self._email_body(approval, approval_url)
        delivered: list[str] = []

        if approval.manager_email:
            logger.info(
                "Sending Bitrix approval mail | lead_id=%s to=%s approval_id=%s",
                approval.bitrix_lead_id,
                approval.manager_email,
                approval.id,
            )
            try:
                if await self.bitrix.send_mail(
                    to_email=approval.manager_email, subject=subject, body=body
                ):
                    delivered.append("bitrix_mail")
            except Exception:
                logger.exception(
                    "Bitrix approval mail raised | approval_id=%s", approval.id
                )

        if not delivered and approval.manager_user_id:
            try:
                if await self.bitrix.notify_user(
                    user_id=approval.manager_user_id,
                    message=f"{subject}\n{approval_url}",
                ):
                    delivered.append("bitrix_chat")
            except Exception:
                logger.exception(
                    "Bitrix approval notification raised | approval_id=%s", approval.id
                )

        if not delivered and approval.manager_email:
            try:
                email_client = get_email_client(self.settings)
                email_client.send_payment_request(
                    to_email=approval.manager_email,
                    customer_name=approval.manager_name or "Manager",
                    payment_url=approval_url,
                )
                delivered.append("email_client")
            except Exception:
                logger.exception(
                    "Fallback email client failed | approval_id=%s", approval.id
                )

        return delivered

    def _email_body(self, approval: PriceApproval, approval_url: str) -> str:
        lines = [
            f"Hello {approval.manager_name or 'Manager'},",
            "",
            "A payment link was requested at a selling price below the catalog minimum.",
            "Please review and approve or reject it.",
            "",
            f"Lead: {approval.lead_title} (#{approval.bitrix_lead_id})",
            f"Owner: {approval.owner_name or approval.owner_user_id or '-'}",
            f"Proposed total: {approval.total_payable} {approval.currency}",
            f"Catalog minimum total: {approval.catalog_minimum_total} {approval.currency}",
            "",
            "Courses:",
        ]
        for line in (approval.lines_payload or {}).get("lines") or []:
            catalog = line.get("catalog_min_price") or "missing"
            lines.append(
                f"- {line.get('product_name')} × {line.get('quantity')} | "
                f"selling {line.get('selling_price')} | catalog min {catalog} | "
                f"{'BELOW MIN' if line.get('below_minimum') else 'OK'}"
            )
        lines.extend(
            [
                "",
                f"Open approval page: {approval_url}",
                "",
                "If you approve, the system will create the Estimate and send the payment link in Bitrix.",
            ]
        )
        return "\n".join(lines)

    async def decide(
        self,
        token: str,
        *,
        approve: bool,
        note: str | None = None,
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
        self.db.commit()
        self.db.refresh(approval)

        if approve:
            comment = (
                f"Discount APPROVED by manager ({approval.manager_email or 'unknown'}).\n"
                f"Proposed total {approval.total_payable} {approval.currency} "
                f"(catalog min {approval.catalog_minimum_total}).\n"
                "Payment link will be generated."
            )
        else:
            comment = (
                f"Discount REJECTED by manager ({approval.manager_email or 'unknown'}).\n"
                f"Reason note: {approval.decision_note or '-'}\n"
                "No payment link was sent."
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
