"""Central workflow orchestration."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.base import PaymentWebhookData
from app.integrations.factory import get_bitrix_client, get_email_client, get_paymob_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import SOURCE_FINANCE_DEAL, SOURCE_LEAD, PaymentSession
from app.models.payment_transaction import PaymentTransaction
from app.services.estimate_price_gate import (
    PriceGateResult,
    ProductLine,
    evaluate_price_gate,
    minimal_pricing_snapshot,
    pricing_snapshot_from_gate,
    product_rows_for_estimate,
    serialize_pricing_snapshot,
)
from app.services.installment_plan import (
    evaluate_installment_policy,
    installment_policy_payload,
    persist_installment_plan,
    resolve_first_charge_for_workflow,
    validate_installment_plan,
)
from app.services.invoice_service import InvoiceService
from app.services.paymob_mapper import apply_paymob_fields
from app.services.payment_session_service import PaymentSessionService
from app.services.payment_threshold_service import PaymentThresholdService
from app.services.price_approval_service import PriceApprovalPending, PriceApprovalService

logger = logging.getLogger(__name__)


def _bitrix_user_email_name(user: dict) -> tuple[str | None, str | None]:
    raw_email = user.get("EMAIL")
    email = None
    if isinstance(raw_email, str) and raw_email:
        email = raw_email
    elif isinstance(raw_email, list) and raw_email:
        first = raw_email[0]
        email = first.get("VALUE") if isinstance(first, dict) else str(first)
    name = " ".join(
        part for part in (user.get("NAME"), user.get("LAST_NAME")) if part
    ).strip() or None
    return (email or None, name)


def _format_price_lines(gate: PriceGateResult) -> str:
    if not gate.lines:
        return "none"
    parts = []
    for line in gate.lines:
        catalog = (
            f"{line.catalog_min_price:.2f}"
            if line.catalog_min_price is not None
            else "missing"
        )
        if line.catalog_min_price is None:
            status = "no_catalog"
        elif line.is_below_minimum:
            status = "below_min"
        else:
            status = "ok"
        parts.append(
            f"{line.product_name}[sell={line.selling_price:.2f} min={catalog} qty={line.quantity:g} {status}]"
        )
    return "; ".join(parts)


class WorkflowOrchestrator:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.bitrix = get_bitrix_client(self.settings)
        self.paymob = get_paymob_client(self.settings)
        self.email = get_email_client(self.settings)
        self.session_service = PaymentSessionService(db, self.settings)
        self.invoice_service = InvoiceService(db, self.settings)
        self.threshold_service = PaymentThresholdService(db, self.settings)
        self.approval_service = PriceApprovalService(db, self.settings)

    def get_or_create_workflow(self, lead_id: int) -> CustomerWorkflow:
        workflow = self.db.scalar(
            select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == lead_id)
        )
        if workflow:
            return workflow

        workflow = CustomerWorkflow(bitrix_lead_id=lead_id)
        self.db.add(workflow)
        self.db.flush()
        return workflow

    def note_lead_stage(self, lead_id: int, stage_id: str) -> None:
        """Track the lead's stage without creating a workflow for unrelated leads."""
        workflow = self.db.scalar(
            select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == lead_id)
        )
        if not workflow or workflow.bitrix_lead_stage_id == stage_id:
            return
        workflow.bitrix_lead_stage_id = stage_id
        self.db.commit()

    async def announce_payment_link(
        self,
        session: PaymentSession,
        *,
        entity_type: str,
        entity_id: int,
        force: bool = False,
    ) -> bool:
        """Comment the link on the CRM entity once per session, unless forced.

        Never posts a link that is already inactive. When a previous session was
        replaced, always force a fresh comment so Bitrix is not left with only a dead URL.
        """
        replaced = bool(getattr(session, "_replaced_previous_link", False))
        if replaced:
            force = True

        active = self.session_service.get_active_session_by_token(session.token)
        if not active:
            logger.warning(
                "SKIP Bitrix payment-link comment | token=%s... reason=session_not_active",
                session.token[:8],
            )
            return False

        if session.link_commented_at and not force:
            return False

        payment_url = self.session_service.build_payment_url(session.token)
        workflow = session.workflow
        minimum = workflow.minimum_due(self.settings.payment_required_percent)
        prefix = ""
        if replaced:
            prefix = (
                "Updated payment link (any earlier payment links for this record "
                "are no longer valid):\n"
            )
        elif force:
            prefix = "Payment reminder — current link:\n"
        comment = (
            f"{prefix}"
            f"Payment link: {payment_url}\n"
            f"Outstanding: {workflow.remaining_balance:.2f} {workflow.currency}\n"
            f"Minimum payable now: {minimum:.2f} {workflow.currency}"
        )
        try:
            await self.bitrix.add_timeline_comment(
                entity_type=entity_type,
                entity_id=entity_id,
                comment=comment,
            )
        except Exception:
            logger.exception(
                "Failed to post payment link comment on Bitrix %s %s", entity_type, entity_id
            )
            return False

        session.link_commented_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(
            "Payment link commented on Bitrix %s %s | token=%s... replaced=%s",
            entity_type.lower(),
            entity_id,
            session.token[:8],
            replaced,
        )
        return True

    def get_workflow_by_finance_deal(self, finance_deal_id: int) -> CustomerWorkflow | None:
        return self.db.scalar(
            select(CustomerWorkflow).where(CustomerWorkflow.finance_deal_id == finance_deal_id)
        )

    async def sync_workflow_from_lead(
        self,
        workflow: CustomerWorkflow,
        lead: dict | None = None,
    ) -> CustomerWorkflow:
        lead = lead or await self.bitrix.get_lead(workflow.bitrix_lead_id)
        workflow.total_amount = self.bitrix.extract_lead_amount(lead)
        email, name = self.bitrix.extract_customer_details(lead)
        workflow.customer_email = email
        workflow.customer_name = name
        phones = lead.get("PHONE") or []
        if isinstance(phones, list) and phones:
            workflow.customer_phone = phones[0].get("VALUE")
        elif isinstance(phones, str):
            workflow.customer_phone = phones
        workflow.currency = lead.get("CURRENCY_ID") or self.settings.default_currency
        workflow.bitrix_lead_stage_id = lead.get("STATUS_ID")
        workflow.bitrix_lead_payload = lead
        workflow.lead_synced_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    async def _enforce_price_gate_and_create_estimate(
        self,
        workflow: CustomerWorkflow,
        *,
        lead: dict | None = None,
    ) -> None:
        """On payment stage: compare catalog prices, create Estimate, then allow payment link."""
        lead_id = workflow.bitrix_lead_id
        if not self.settings.bitrix_price_gate_enabled:
            logger.info(
                "SKIP price gate + estimate | lead_id=%s reason=BITRIX_PRICE_GATE_ENABLED_false",
                lead_id,
            )
            return

        lead = lead or await self.bitrix.get_lead(lead_id)
        title = str(lead.get("TITLE") or lead.get("title") or f"Lead {lead_id}")
        currency = workflow.currency or self.settings.default_currency

        logger.info(
            "START payment-stage checks | lead_id=%s title=%s amount=%s %s gate=on",
            lead_id,
            title,
            workflow.total_amount,
            currency,
        )

        rows = await self.bitrix.list_product_rows(owner_type="L", owner_id=lead_id)
        logger.info(
            "Products loaded | lead_id=%s count=%s",
            lead_id,
            len(rows),
        )

        catalog_prices: dict[int, Decimal] = {}
        for row in rows:
            raw_id = row.get("productId") if "productId" in row else row.get("PRODUCT_ID")
            try:
                product_id = int(raw_id or 0)
            except (TypeError, ValueError):
                product_id = 0
            if product_id <= 0 or product_id in catalog_prices:
                continue
            price = await self.bitrix.get_catalog_min_price(product_id)
            name = (
                row.get("productName")
                or row.get("PRODUCT_NAME")
                or f"product:{product_id}"
            )
            if price is not None:
                catalog_prices[product_id] = price
                logger.info(
                    "Catalog price | lead_id=%s product_id=%s name=%s min=%s %s",
                    lead_id,
                    product_id,
                    name,
                    f"{price:.2f}",
                    currency,
                )
            else:
                logger.warning(
                    "Catalog price missing | lead_id=%s product_id=%s name=%s",
                    lead_id,
                    product_id,
                    name,
                )

        gate = evaluate_price_gate(rows, catalog_prices)
        comment = gate.summary_comment(currency=currency, amount_paid=workflow.amount_paid)
        logger.info(
            "Price comparison | lead_id=%s result=%s total=%s catalog_min_total=%s lines=%s",
            lead_id,
            "PASS" if gate.ok else "FAIL",
            f"{gate.total_payable:.2f}",
            f"{gate.catalog_minimum_total:.2f}",
            _format_price_lines(gate),
        )
        if gate.reason and not gate.ok:
            logger.info(
                "Price comparison detail | lead_id=%s reason=%s",
                lead_id,
                gate.reason,
            )

        if not gate.ok and (gate.missing_catalog or not gate.lines):
            await self._post_gate_comment(
                workflow, comment, state_key=f"blocked|{comment}"
            )
            logger.warning(
                "FAIL payment-stage | lead_id=%s step=products_or_catalog reason=%s",
                lead_id,
                gate.reason,
            )
            raise ValueError(gate.reason)

        # Prefer product-derived total whenever we have product lines.
        if gate.total_payable > 0:
            workflow.total_amount = gate.total_payable
            if not workflow.pricing_snapshot:
                workflow.pricing_snapshot = pricing_snapshot_from_gate(
                    gate, currency=currency
                )
            self.db.commit()
            self.db.refresh(workflow)

        # Always create/reuse Estimate once products are present (pass or below-min).
        await self._ensure_estimate_for_gate(
            workflow,
            lead=lead,
            gate_total=gate.total_payable,
            gate_tax=gate.tax_total,
            product_rows=product_rows_for_estimate(gate.lines),
            comment=comment,
            awaiting_approval=not gate.ok,
        )

        if not gate.ok:
            logger.info(
                "Estimate ready — awaiting discount approval | lead_id=%s estimate_id=%s",
                lead_id,
                workflow.bitrix_estimate_id,
            )
            policy = evaluate_installment_policy(
                lead,
                self.settings,
                payable_total=gate.total_payable or Decimal(workflow.total_amount or 0),
            )
            approval = await self.approval_service.request_manager_approval(
                workflow,
                gate,
                lead=lead,
                installment_policy=(
                    installment_policy_payload(policy) if policy.needs_approval else None
                ),
            )
            approval_url = self.approval_service.build_approval_url(approval.token)
            logger.warning(
                "PENDING manager approval | lead_id=%s estimate_id=%s approval_id=%s "
                "manager=%s selling=%s catalog_min=%s url=%s",
                lead_id,
                workflow.bitrix_estimate_id,
                approval.id,
                approval.manager_email,
                approval.total_payable,
                approval.catalog_minimum_total,
                approval_url,
            )
            raise PriceApprovalPending(
                (
                    "Selling price is below the catalog minimum. "
                    f"Manager approval requested ({approval.manager_email})."
                ),
                approval_url=approval_url,
                approval_id=approval.id,
            )

        logger.info(
            "OK payment-stage checks | lead_id=%s estimate_id=%s total=%s %s next=send_payment_link",
            lead_id,
            workflow.bitrix_estimate_id,
            gate.total_payable,
            currency,
        )

    async def _capture_first_payment_snapshots(
        self,
        workflow: CustomerWorkflow,
        *,
        lead: dict,
        skip_installment_policy: bool = False,
    ) -> None:
        """Freeze pricing + installment plan once at first payment-link creation."""
        currency = workflow.currency or self.settings.default_currency
        if not workflow.pricing_snapshot:
            workflow.pricing_snapshot = minimal_pricing_snapshot(
                currency=currency,
                total_payable=Decimal(workflow.total_amount or 0),
            )
            self.db.commit()
            self.db.refresh(workflow)

        if not workflow.installments:
            validation = validate_installment_plan(
                lead,
                self.settings,
                payable_total=Decimal(workflow.total_amount or 0),
            )
            if validation.indicated and not validation.ok:
                message = (
                    "Installment plan is incomplete or invalid. Fix Bitrix installment "
                    "amounts and due dates before generating a payment link.\n"
                    + "\n".join(f"- {err}" for err in validation.errors)
                )
                try:
                    await self.bitrix.add_timeline_comment(
                        entity_type="LEAD",
                        entity_id=workflow.bitrix_lead_id,
                        comment=message,
                    )
                except Exception:
                    logger.exception(
                        "Failed to post installment validation comment on lead %s",
                        workflow.bitrix_lead_id,
                    )
                raise ValueError(message)

            if validation.indicated and validation.ok:
                persist_installment_plan(self.db, workflow, validation.slots)

        if skip_installment_policy:
            return

        policy = evaluate_installment_policy(
            lead,
            self.settings,
            payable_total=Decimal(workflow.total_amount or 0),
        )
        if not policy.needs_approval:
            return

        approval = await self.approval_service.request_manager_approval(
            workflow,
            gate=None,
            lead=lead,
            installment_policy=installment_policy_payload(policy),
        )
        approval_url = self.approval_service.build_approval_url(approval.token)
        logger.warning(
            "PENDING installment policy approval | lead_id=%s approval_id=%s "
            "manager=%s reasons=%s url=%s",
            workflow.bitrix_lead_id,
            approval.id,
            approval.manager_email,
            "; ".join(policy.reasons),
            approval_url,
        )
        raise PriceApprovalPending(
            (
                "Installment plan needs manager approval. "
                f"Manager approval requested ({approval.manager_email})."
            ),
            approval_url=approval_url,
            approval_id=approval.id,
        )

    async def _post_gate_comment(
        self, workflow: CustomerWorkflow, body: str, *, state_key: str
    ) -> bool:
        """Post a price-gate comment unless the same gate outcome was already posted.

        Each comment updates the lead, which fires ONCRMLEADUPDATE and re-runs this
        stage, so re-posting an unchanged outcome loops forever. The key describes the
        outcome rather than the wording, so the "created" and "already exists" variants
        of one estimate count as the same comment.
        """
        lead_id = workflow.bitrix_lead_id
        digest = hashlib.sha256(state_key.encode("utf-8")).hexdigest()
        if workflow.last_gate_comment_hash == digest:
            logger.info(
                "SKIP gate comment | lead_id=%s reason=unchanged_since_last_run",
                lead_id,
            )
            return False

        try:
            await self.bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=lead_id,
                comment=body,
            )
        except Exception:
            logger.exception("Failed to post price-gate comment on lead %s", lead_id)
            return False

        workflow.last_gate_comment_hash = digest
        self.db.commit()
        self.db.refresh(workflow)
        return True

    async def _ensure_estimate_for_gate(
        self,
        workflow: CustomerWorkflow,
        *,
        lead: dict,
        gate_total: Decimal,
        gate_tax: Decimal,
        product_rows: list[dict],
        comment: str,
        awaiting_approval: bool = False,
    ) -> None:
        lead_id = workflow.bitrix_lead_id
        currency = workflow.currency or self.settings.default_currency
        next_step = (
            "awaiting manager approval"
            if awaiting_approval
            else "payment link will be sent"
        )

        if workflow.bitrix_estimate_id:
            logger.info(
                "SKIP new estimate | lead_id=%s estimate_id=%s reason=already_exists next=%s",
                lead_id,
                workflow.bitrix_estimate_id,
                next_step,
            )
            await self._post_gate_comment(
                workflow,
                (
                    f"{comment}\n\n"
                    f"Estimate already exists: #{workflow.bitrix_estimate_id}. "
                    f"{next_step.capitalize()}."
                ),
                state_key=f"{workflow.bitrix_estimate_id}|{next_step}|{comment}",
            )
            return

        contact_raw = lead.get("CONTACT_ID") or lead.get("contactId")
        try:
            contact_id = int(contact_raw) if contact_raw not in (None, "", "0") else None
        except (TypeError, ValueError):
            contact_id = None

        title = str(lead.get("TITLE") or lead.get("title") or f"Estimate for lead {lead_id}")
        logger.info(
            "Creating Bitrix estimate | lead_id=%s title=%s total=%s tax=%s products=%s",
            lead_id,
            title,
            f"{gate_total:.2f}",
            f"{gate_tax:.2f}",
            len(product_rows),
        )
        estimate_id = await self.bitrix.create_estimate(
            lead_id=lead_id,
            title=f"Estimate — {title}",
            currency=currency,
            opportunity=gate_total,
            tax_value=gate_tax,
            contact_id=contact_id,
            product_rows=product_rows,
            comments=comment,
        )
        workflow.bitrix_estimate_id = estimate_id
        self.db.commit()
        self.db.refresh(workflow)

        await self._post_gate_comment(
            workflow,
            f"{comment}\n\nEstimate #{estimate_id} created. {next_step.capitalize()}.",
            state_key=f"{estimate_id}|{next_step}|{comment}",
        )
        logger.info(
            "OK estimate created | lead_id=%s estimate_id=%s total=%s %s next=%s",
            lead_id,
            estimate_id,
            f"{gate_total:.2f}",
            currency,
            next_step,
        )

    async def initiate_payment_from_lead(
        self,
        lead_id: int,
        *,
        customer_email: str | None = None,
        customer_name: str | None = None,
        total_amount: Decimal | None = None,
        lead_data: dict | None = None,
        skip_price_gate: bool = False,
        skip_installment_policy: bool = False,
    ) -> PaymentSession:
        workflow = self.get_or_create_workflow(lead_id)
        explicit_override = (
            customer_email is not None
            and customer_name is not None
            and total_amount is not None
        )
        if explicit_override:
            workflow.customer_email = customer_email
            workflow.customer_name = customer_name
            workflow.total_amount = total_amount
            workflow.currency = self.settings.default_currency
            self.db.commit()
            self.db.refresh(workflow)
        else:
            await self.sync_workflow_from_lead(workflow, lead_data)
            if not skip_price_gate:
                await self._enforce_price_gate_and_create_estimate(
                    workflow, lead=lead_data
                )

        if workflow.total_amount <= 0:
            raise ValueError(
                f"Lead {lead_id} has no payment amount — set OPPORTUNITY "
                f"(or BITRIX_FIELD_LEAD_AMOUNT) in Bitrix before requesting payment"
            )

        # Refresh from Bitrix before cash/online branching so Payment Mode is current.
        # Stale lead payloads caused Paymob emails when mode was Cash.
        try:
            fresh_lead = await self.bitrix.get_lead(lead_id)
            if fresh_lead:
                lead_data = fresh_lead
                workflow.bitrix_lead_payload = fresh_lead
                self.db.commit()
        except Exception:
            logger.exception(
                "Could not refresh Bitrix lead %s before payment-mode check", lead_id
            )

        lead = lead_data or workflow.bitrix_lead_payload or {}
        await self._capture_first_payment_snapshots(
            workflow,
            lead=lead,
            skip_installment_policy=skip_installment_policy,
        )

        plan = resolve_first_charge_for_workflow(
            workflow, lead=lead, settings=self.settings
        )
        if plan.amount <= 0:
            raise ValueError(
                f"Lead {lead_id} has no chargeable amount after installment resolution"
            )

        logger.info(
            "Charge plan | lead_id=%s source=%s amount=%s %s installment_1=%s "
            "installments=%s locked=%s",
            lead_id,
            plan.source,
            f"{plan.amount:.2f}",
            workflow.currency,
            f"{plan.installment_1:.2f}" if plan.installment_1 is not None else "-",
            plan.installment_count if plan.installment_count is not None else "-",
            plan.locked,
        )

        from app.services.cash_collection_service import (
            CashCollectionQueued,
            CashCollectionService,
        )
        from app.services.installment_plan import charge_installment_number_for_workflow
        from app.services.payment_mode import resolve_is_cash_payment_mode

        installment_number = charge_installment_number_for_workflow(workflow)
        if installment_number is None and plan.source == "installment_1":
            installment_number = 1
        number_for_mode = installment_number or 1
        if await resolve_is_cash_payment_mode(
            lead,
            installment_number=number_for_mode,
            settings=self.settings,
            bitrix=self.bitrix,
        ):
            expired = self.session_service.expire_active_sessions_for_workflow(workflow)
            if expired:
                logger.info(
                    "Expired %s online payment session(s) before cash queue | lead_id=%s",
                    expired,
                    lead_id,
                )
            cash = CashCollectionService(self.db, self.settings)
            collection = cash.enqueue_from_workflow(
                workflow,
                lead=lead,
                due_amount=plan.amount,
                installment_number=number_for_mode,
            )
            comment = (
                f"Cash collection queued (Cash Desk)\n"
                f"Installment {collection.installment_number}: "
                f"{collection.due_amount} {collection.currency}\n"
                f"Customer: {collection.customer_name or '-'}\n"
                f"No Paymob link was created — collect cash in Cash Desk."
            )
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type="LEAD",
                    entity_id=lead_id,
                    comment=comment,
                )
            except Exception:
                logger.exception(
                    "Failed to comment cash queue on lead %s", lead_id
                )
            logger.info(
                "Cash queued | lead_id=%s installment=%s collection_id=%s amount=%s",
                lead_id,
                number_for_mode,
                collection.id,
                collection.due_amount,
            )
            raise CashCollectionQueued(collection)

        session = await self.session_service.get_or_create_reusable_session(
            workflow,
            charge_amount=plan.amount,
            charge_source=plan.source,
            amount_locked=plan.locked,
            installment_number=installment_number,
        )
        payment_url = self.session_service.build_payment_url(session.token)

        await self.announce_payment_link(session, entity_type="LEAD", entity_id=lead_id)

        if workflow.customer_email:
            self.email.send_payment_request(
                to_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
            )
            workflow.last_reminder_at = datetime.now(timezone.utc)
            self.db.commit()

        logger.info(
            "Payment link created for lead %s — estimate_id=%s token %s...",
            lead_id,
            workflow.bitrix_estimate_id or "-",
            session.token[:8],
        )
        return session

    async def complete_approved_payment(
        self,
        token: str,
        *,
        note: str | None = None,
        product_prices: list[dict] | None = None,
        installment_overrides: list[dict] | None = None,
    ) -> PaymentSession:
        """Manager approved — apply optional overrides, then send payment link."""
        logger.info("START manager approve | token=%s...", token[:8])
        approval = await self.approval_service.decide(token, approve=True, note=note)
        workflow = self.get_or_create_workflow(approval.bitrix_lead_id)
        lead = await self.bitrix.get_lead(approval.bitrix_lead_id)
        await self.sync_workflow_from_lead(workflow, lead)

        payload = dict(approval.lines_payload or {})
        lines_raw = list(payload.get("lines") or [])
        price_map = {
            int(row.get("product_id") or 0): Decimal(str(row.get("selling_price") or "0"))
            for row in (product_prices or [])
            if int(row.get("product_id") or 0) > 0
        }
        if price_map:
            updated_lines = []
            for row in lines_raw:
                product_id = int(row.get("product_id") or 0)
                if product_id in price_map:
                    row = dict(row)
                    new_price = price_map[product_id].quantize(Decimal("0.01"))
                    row["selling_price"] = str(new_price)
                    catalog = row.get("catalog_min_price")
                    if catalog is not None:
                        catalog_dec = Decimal(str(catalog))
                        below = new_price < catalog_dec
                        row["below_minimum"] = below
                        row["discount_amount"] = (
                            str((catalog_dec - new_price).quantize(Decimal("0.01")))
                            if below
                            else None
                        )
                        row["status"] = "BELOW MIN" if below else "OK"
                    else:
                        row["below_minimum"] = False
                        row["status"] = "OK"
                updated_lines.append(row)
            lines_raw = updated_lines
            payload["lines"] = lines_raw
            payload["below_minimum_count"] = sum(
                1 for row in lines_raw if row.get("below_minimum")
            )
            payload["ok_count"] = len(lines_raw) - payload["below_minimum_count"]
            approval.lines_payload = payload

        product_lines: list[ProductLine] = []
        for row in lines_raw:
            catalog = row.get("catalog_min_price")
            product_lines.append(
                ProductLine(
                    product_id=int(row.get("product_id") or 0),
                    product_name=str(row.get("product_name") or "Course"),
                    quantity=Decimal(str(row.get("quantity") or "1")),
                    selling_price=Decimal(str(row.get("selling_price") or "0")),
                    tax_rate=Decimal(str(row.get("tax_rate") or "0")),
                    tax_included=bool(row.get("tax_included")),
                    catalog_min_price=Decimal(str(catalog)) if catalog is not None else None,
                )
            )

        if product_lines:
            snapshot = serialize_pricing_snapshot(
                product_lines,
                currency=approval.currency or self.settings.default_currency,
            )
            workflow.total_amount = Decimal(snapshot["total_payable"])
            workflow.pricing_snapshot = snapshot
            approval.total_payable = snapshot["total_payable"]
        else:
            workflow.total_amount = Decimal(approval.total_payable)
        workflow.currency = approval.currency or self.settings.default_currency
        self.db.commit()
        self.db.refresh(workflow)
        self.db.refresh(approval)

        override_slots = self._merge_installment_overrides(
            lead=lead,
            workflow=workflow,
            installment_overrides=installment_overrides or [],
        )
        if override_slots:
            persist_installment_plan(self.db, workflow, override_slots, replace=True)
            # Keep lead payload in sync for any later reads before freeze path.
            for slot in override_slots:
                amount_field, date_field = self._installment_field_codes(slot.number)
                if amount_field and slot.amount is not None:
                    lead[amount_field] = str(slot.amount)
                if date_field and slot.due_date is not None:
                    lead[date_field] = slot.due_date.isoformat()
            workflow.bitrix_lead_payload = lead
            self.db.commit()
            self.db.refresh(workflow)

        changed = await self._apply_manager_changes_to_bitrix(
            workflow=workflow,
            approval=approval,
            lead=lead,
            product_prices=product_prices or [],
            installment_overrides=installment_overrides or [],
            product_lines=product_lines,
        )
        if changed:
            await self._notify_owner_of_manager_changes(
                workflow,
                approval,
                changed=changed,
                approved=True,
            )

        tax_total = Decimal("0.00")
        for line in product_lines:
            if line.tax_included or line.tax_rate <= 0:
                continue
            qty = line.quantity if line.quantity > 0 else Decimal("1")
            base = (line.selling_price * qty).quantize(Decimal("0.01"))
            tax_total += (base * line.tax_rate / Decimal("100")).quantize(Decimal("0.01"))

        comment = (
            f"Manager-approved payment\n"
            f"Total payable: {workflow.total_amount:.2f} {workflow.currency}\n"
            f"Catalog minimum total: {approval.catalog_minimum_total} {workflow.currency}"
        )
        if product_lines or workflow.bitrix_estimate_id:
            await self._ensure_estimate_for_gate(
                workflow,
                lead=lead,
                gate_total=workflow.total_amount,
                gate_tax=tax_total,
                product_rows=product_rows_for_estimate(product_lines),
                comment=comment,
                awaiting_approval=False,
            )
        logger.info(
            "OK manager approve | lead_id=%s estimate_id=%s approval_id=%s next=send_payment_link",
            approval.bitrix_lead_id,
            workflow.bitrix_estimate_id,
            approval.id,
        )
        try:
            lead = await self.bitrix.get_lead(approval.bitrix_lead_id) or lead
        except Exception:
            logger.exception(
                "Could not refresh lead %s after manager approve",
                approval.bitrix_lead_id,
            )
        return await self.initiate_payment_from_lead(
            approval.bitrix_lead_id,
            lead_data=lead,
            skip_price_gate=True,
            skip_installment_policy=True,
        )

    def _installment_field_codes(self, number: int) -> tuple[str, str]:
        mapping = {
            1: (
                self.settings.bitrix_field_installment_1,
                self.settings.bitrix_field_installment_1_date,
            ),
            2: (
                self.settings.bitrix_field_installment_2,
                self.settings.bitrix_field_installment_2_due_date,
            ),
            3: (
                self.settings.bitrix_field_installment_3,
                self.settings.bitrix_field_installment_3_due_date,
            ),
            4: (
                self.settings.bitrix_field_installment_4,
                self.settings.bitrix_field_installment_4_due_date,
            ),
        }
        return mapping.get(number, ("", ""))

    def _merge_installment_overrides(
        self,
        *,
        lead: dict,
        workflow: CustomerWorkflow,
        installment_overrides: list[dict],
    ) -> list:
        from app.services.installment_notices import parse_bitrix_date
        from app.services.installment_plan import ParsedInstallment, parse_installment_candidates

        base = {
            s.number: s
            for s in parse_installment_candidates(lead, self.settings)
        }
        for row in workflow.installments or []:
            base[row.installment_number] = ParsedInstallment(
                number=row.installment_number,
                amount=Decimal(row.amount),
                due_date=row.due_date,
            )
        for raw in installment_overrides:
            number = int(raw.get("number") or 0)
            if number < 1 or number > 4:
                continue
            current = base.get(number)
            amount = current.amount if current else None
            due = current.due_date if current else None
            if raw.get("amount") not in (None, ""):
                amount = Decimal(str(raw["amount"])).quantize(Decimal("0.01"))
            if raw.get("due_date"):
                due = parse_bitrix_date(raw["due_date"])
            if amount is None or due is None:
                continue
            base[number] = ParsedInstallment(number=number, amount=amount, due_date=due)
        return [base[n] for n in sorted(base) if base[n].amount is not None and base[n].due_date]

    def _product_lines_from_approval(
        self,
        approval,
        *,
        product_prices: list[dict] | None = None,
    ) -> list[ProductLine]:
        payload = approval.lines_payload or {}
        price_map = {
            int(row.get("product_id") or 0): Decimal(str(row.get("selling_price") or "0"))
            for row in (product_prices or [])
            if int(row.get("product_id") or 0) > 0
        }
        for row in payload.get("manager_suggested_prices") or []:
            try:
                pid = int(row.get("product_id") or 0)
            except (TypeError, ValueError):
                continue
            if pid > 0 and row.get("selling_price") not in (None, ""):
                price_map.setdefault(pid, Decimal(str(row["selling_price"])))

        lines: list[ProductLine] = []
        for row in payload.get("lines") or []:
            product_id = int(row.get("product_id") or 0)
            catalog = row.get("catalog_min_price")
            selling = price_map.get(product_id)
            if selling is None:
                selling = Decimal(str(row.get("selling_price") or "0"))
            lines.append(
                ProductLine(
                    product_id=product_id,
                    product_name=str(row.get("product_name") or "Course"),
                    quantity=Decimal(str(row.get("quantity") or "1")),
                    selling_price=selling.quantize(Decimal("0.01")),
                    tax_rate=Decimal(str(row.get("tax_rate") or "0")),
                    tax_included=bool(row.get("tax_included")),
                    catalog_min_price=Decimal(str(catalog)) if catalog is not None else None,
                )
            )
        return lines

    def _money_field_value(self, amount: Decimal, currency: str) -> str:
        return f"{amount.quantize(Decimal('0.01'))}|{currency or self.settings.default_currency}"

    async def _apply_manager_changes_to_bitrix(
        self,
        *,
        workflow: CustomerWorkflow,
        approval,
        lead: dict,
        product_prices: list[dict],
        installment_overrides: list[dict],
        product_lines: list[ProductLine] | None,
    ) -> dict[str, Any]:
        """Write manager amount/date/price changes to Estimate + lead Payment Section."""
        changed: dict[str, Any] = {
            "prices": [],
            "amounts": [],
            "dates": [],
            "estimate_id": None,
        }
        currency = approval.currency or workflow.currency or self.settings.default_currency
        payload = approval.lines_payload or {}
        suggested_prices = list(product_prices or []) or list(
            payload.get("manager_suggested_prices") or []
        )

        lines = product_lines or self._product_lines_from_approval(
            approval, product_prices=suggested_prices
        )
        if suggested_prices and lines:
            rows = product_rows_for_estimate(lines)
            snapshot = serialize_pricing_snapshot(lines, currency=currency)
            tax_total = Decimal(snapshot.get("vat_total") or "0")
            opportunity = Decimal(snapshot["total_payable"])
            estimate_id = workflow.bitrix_estimate_id
            try:
                if estimate_id:
                    await self.bitrix.update_estimate(
                        estimate_id,
                        currency=currency,
                        opportunity=opportunity,
                        tax_value=tax_total,
                        product_rows=rows,
                        comments=(
                            f"Updated from manager approval recommendation "
                            f"({approval.manager_email or 'manager'})."
                        ),
                    )
                else:
                    contact_raw = lead.get("CONTACT_ID") or lead.get("contactId")
                    try:
                        contact_id = (
                            int(contact_raw)
                            if contact_raw not in (None, "", 0, "0")
                            else None
                        )
                    except (TypeError, ValueError):
                        contact_id = None
                    estimate_id = await self.bitrix.create_estimate(
                        lead_id=approval.bitrix_lead_id,
                        title=f"Estimate - {approval.lead_title or approval.bitrix_lead_id}",
                        currency=currency,
                        opportunity=opportunity,
                        tax_value=tax_total,
                        contact_id=contact_id,
                        product_rows=rows,
                        comments="Created from manager approval recommendation.",
                    )
                    workflow.bitrix_estimate_id = estimate_id
                    self.db.commit()
                try:
                    await self.bitrix.set_lead_product_rows(approval.bitrix_lead_id, rows)
                except Exception:
                    logger.exception(
                        "Failed to sync lead product rows after manager price change | lead_id=%s",
                        approval.bitrix_lead_id,
                    )
                changed["estimate_id"] = estimate_id
                changed_ids = {
                    int(p.get("product_id") or 0)
                    for p in suggested_prices
                    if int(p.get("product_id") or 0) > 0
                }
                changed["prices"] = [
                    {
                        "product_id": line.product_id,
                        "product_name": line.product_name,
                        "selling_price": str(line.selling_price),
                    }
                    for line in lines
                    if line.product_id in changed_ids
                ]
            except Exception:
                logger.exception(
                    "Failed to update Bitrix estimate after manager price change | lead_id=%s",
                    approval.bitrix_lead_id,
                )

        overrides = list(installment_overrides or [])
        for row in payload.get("manager_suggested_amounts") or []:
            overrides.append({"number": row.get("number"), "amount": row.get("amount")})
        for row in payload.get("manager_suggested_dates") or []:
            overrides.append({"number": row.get("number"), "due_date": row.get("due_date")})

        lead_fields: dict[str, Any] = {}
        seen_amount: set[int] = set()
        seen_date: set[int] = set()
        for raw in overrides:
            try:
                number = int(raw.get("number") or 0)
            except (TypeError, ValueError):
                continue
            if number < 1 or number > 4:
                continue
            amount_field, date_field = self._installment_field_codes(number)
            if raw.get("amount") not in (None, "") and amount_field and number not in seen_amount:
                amount = Decimal(str(raw["amount"])).quantize(Decimal("0.01"))
                lead_fields[amount_field] = self._money_field_value(amount, currency)
                lead[amount_field] = lead_fields[amount_field]
                changed["amounts"].append({"number": number, "amount": str(amount)})
                seen_amount.add(number)
            if raw.get("due_date") and date_field and number not in seen_date:
                due = str(raw["due_date"]).strip()
                lead_fields[date_field] = due
                lead[date_field] = due
                changed["dates"].append({"number": number, "due_date": due})
                seen_date.add(number)

        if lead_fields:
            try:
                await self.bitrix.update_lead_fields(approval.bitrix_lead_id, lead_fields)
                workflow.bitrix_lead_payload = lead
                self.db.commit()
            except Exception:
                logger.exception(
                    "Failed to write manager installment changes to lead %s",
                    approval.bitrix_lead_id,
                )

        if not (changed["prices"] or changed["amounts"] or changed["dates"]):
            return {}
        return changed

    async def _notify_lead_owner(
        self,
        workflow: CustomerWorkflow,
        approval,
        *,
        subject: str,
        body: str,
    ) -> None:
        try:
            lead = await self.bitrix.get_lead(workflow.bitrix_lead_id)
        except Exception:
            logger.exception(
                "Could not load lead %s to notify owner",
                workflow.bitrix_lead_id,
            )
            lead = None

        owner_id = 0
        if lead:
            owner_raw = lead.get("ASSIGNED_BY_ID") or lead.get("assignedById")
            try:
                owner_id = int(owner_raw or 0)
            except (TypeError, ValueError):
                owner_id = 0
        if owner_id <= 0 and approval.owner_user_id:
            try:
                owner_id = int(approval.owner_user_id)
            except (TypeError, ValueError):
                owner_id = 0

        if owner_id <= 0:
            logger.info(
                "No responsible person on lead %s — skip owner chat/email",
                workflow.bitrix_lead_id,
            )
            return

        chat_text = f"{subject}\n\n{body}"
        try:
            await self.bitrix.notify_user(user_id=owner_id, message=chat_text)
        except Exception:
            logger.exception(
                "Failed Bitrix owner chat to user %s for lead %s",
                owner_id,
                workflow.bitrix_lead_id,
            )

        agent_email = None
        agent_name = None
        try:
            user = await self.bitrix.get_user(owner_id)
        except Exception:
            logger.exception("Failed to load Bitrix user %s for owner email", owner_id)
            user = None
        if user:
            agent_email, agent_name = _bitrix_user_email_name(user)
        if not agent_email:
            logger.info(
                "Responsible person %s has no email — chat only | lead_id=%s",
                owner_id,
                workflow.bitrix_lead_id,
            )
            return
        try:
            sent = self.email.send_agent_payment_notice(
                to_email=agent_email,
                agent_name=agent_name,
                subject=subject,
                body=body,
            )
            if sent:
                logger.info(
                    "Owner notice emailed | to=%s lead_id=%s subject=%s",
                    agent_email,
                    workflow.bitrix_lead_id,
                    subject[:60],
                )
        except Exception:
            logger.exception(
                "Failed SendGrid owner notice | to=%s lead_id=%s",
                agent_email,
                workflow.bitrix_lead_id,
            )

    async def _notify_owner_of_manager_changes(
        self,
        workflow: CustomerWorkflow,
        approval,
        *,
        changed: dict[str, Any],
        approved: bool,
    ) -> None:
        preferred = self._format_suggested_prices(approval)
        if not preferred and changed:
            parts = []
            for row in changed.get("prices") or []:
                parts.append(
                    f"  • {row.get('product_name')}: {row.get('selling_price')} {approval.currency}"
                )
            for row in changed.get("amounts") or []:
                parts.append(
                    f"  • Installment {row.get('number')}: amount {row.get('amount')} "
                    f"{approval.currency}"
                )
            for row in changed.get("dates") or []:
                parts.append(
                    f"  • Installment {row.get('number')}: due date {row.get('due_date')}"
                )
            preferred = "Manager changes:\n" + "\n".join(parts) if parts else ""
        if not preferred:
            return

        action = "approved with updates" if approved else "updated values"
        subject = (
            f"Manager {action} — {approval.lead_title or f'Lead {approval.bitrix_lead_id}'}"
        )
        body = "\n".join(
            [
                f"The manager ({approval.manager_email or 'unknown'}) changed payment details "
                f"on lead #{approval.bitrix_lead_id}.",
                "",
                preferred,
                "",
                "Bitrix Estimate / Payment Section were updated to match.",
                "Please discuss these values with the client.",
            ]
        )
        await self._notify_lead_owner(workflow, approval, subject=subject, body=body)

    async def reject_price_approval(
        self,
        token: str,
        *,
        note: str | None = None,
        product_prices: list[dict] | None = None,
        installment_overrides: list[dict] | None = None,
        rejected_case: str | None = None,
    ) -> None:
        logger.info("START manager reject | token=%s...", token[:8])
        suggested_dates = []
        suggested_amounts = []
        for row in installment_overrides or []:
            entry: dict = {"number": row.get("number")}
            if row.get("due_date"):
                suggested_dates.append({**entry, "due_date": row.get("due_date")})
            if row.get("amount") is not None and str(row.get("amount")).strip() != "":
                suggested_amounts.append({**entry, "amount": row.get("amount")})
        approval = await self.approval_service.decide(
            token,
            approve=False,
            note=note,
            suggested_prices=product_prices or [],
            suggested_dates=suggested_dates,
            suggested_amounts=suggested_amounts,
            rejected_case=rejected_case,
        )
        workflow = self.get_or_create_workflow(approval.bitrix_lead_id)
        lead: dict = {}
        try:
            lead = await self.bitrix.get_lead(approval.bitrix_lead_id)
            await self.sync_workflow_from_lead(workflow, lead)
        except Exception:
            logger.exception(
                "Could not reload lead %s before applying manager reject changes",
                approval.bitrix_lead_id,
            )
            lead = workflow.bitrix_lead_payload or {}

        changed = await self._apply_manager_changes_to_bitrix(
            workflow=workflow,
            approval=approval,
            lead=lead,
            product_prices=product_prices or [],
            installment_overrides=installment_overrides or [],
            product_lines=None,
        )
        logger.warning(
            "OK manager reject | lead_id=%s approval_id=%s estimate_id=%s note=%s case=%s "
            "bitrix_updated=%s",
            approval.bitrix_lead_id,
            approval.id,
            workflow.bitrix_estimate_id or "-",
            (note or "")[:80],
            rejected_case or "-",
            bool(changed),
        )
        await self._notify_owner_of_rejection(
            workflow, approval, bitrix_updated=bool(changed)
        )

    @staticmethod
    def _format_suggested_prices(approval) -> str:
        """Preferred values the manager set on reject (guidance for the lead owner)."""
        return PriceApprovalService._rejection_preferred_block(approval).rstrip()

    async def _notify_owner_of_rejection(
        self,
        workflow: CustomerWorkflow,
        approval,
        *,
        bitrix_updated: bool = False,
    ) -> None:
        """Tell the lead responsible person the manager rejected approval."""
        kinds = (approval.lines_payload or {}).get("approval_kinds") or ["price"]
        label = (approval.lines_payload or {}).get("rejected_case") or " / ".join(kinds)
        note = approval.decision_note or "-"
        preferred = self._format_suggested_prices(approval)
        subject = f"Payment approval rejected — {approval.lead_title or f'Lead {approval.bitrix_lead_id}'}"
        body_parts = [
            f"Your payment approval request was rejected by the manager "
            f"({approval.manager_email or 'unknown'}).",
            "",
            f"Lead: {approval.lead_title or '-'} (#{approval.bitrix_lead_id})",
            f"Rejected case: {label}",
            f"Proposed total: {approval.total_payable} {approval.currency}",
            f"Manager note: {note}",
        ]
        if preferred:
            body_parts.extend(["", preferred])
        body_parts.append("")
        body_parts.append("No payment link was sent.")
        if bitrix_updated:
            body_parts.append(
                "Bitrix Estimate / Payment Section were updated with the manager's preferred values."
            )
            body_parts.append(
                "Please discuss these values with the client, then move the lead to the "
                "payment stage again when ready."
            )
        else:
            body_parts.append(
                "Please update the lead to match the preferred values above "
                "(and/or the installment plan), then move it to the payment stage again."
            )
        body = "\n".join(body_parts)
        await self._notify_lead_owner(workflow, approval, subject=subject, body=body)

    async def initiate_payment_from_finance_deal(self, finance_deal_id: int) -> PaymentSession:
        workflow = self.get_workflow_by_finance_deal(finance_deal_id)
        if not workflow:
            raise ValueError(f"No workflow found for finance deal {finance_deal_id}")

        if workflow.remaining_balance <= 0 and workflow.amount_paid >= workflow.total_amount:
            raise ValueError(f"Finance deal {finance_deal_id} has no remaining balance")

        lead = workflow.bitrix_lead_payload if isinstance(workflow.bitrix_lead_payload, dict) else {}
        plan = resolve_first_charge_for_workflow(
            workflow, lead=lead, settings=self.settings
        )
        from app.services.cash_collection_service import (
            CashCollectionQueued,
            CashCollectionService,
        )
        from app.services.installment_plan import charge_installment_number_for_workflow
        from app.services.payment_mode import resolve_is_cash_payment_mode

        installment_number = charge_installment_number_for_workflow(workflow)
        if installment_number is None and plan.source == "installment_1":
            installment_number = 1
        number_for_mode = installment_number or 1
        if await resolve_is_cash_payment_mode(
            lead,
            installment_number=number_for_mode,
            settings=self.settings,
            bitrix=self.bitrix,
        ):
            expired = self.session_service.expire_active_sessions_for_workflow(workflow)
            if expired:
                logger.info(
                    "Expired %s online payment session(s) before cash queue | lead_id=%s",
                    expired,
                    lead_id,
                )
            cash = CashCollectionService(self.db, self.settings)
            collection = cash.enqueue_from_workflow(
                workflow,
                lead=lead,
                due_amount=plan.amount,
                installment_number=number_for_mode,
            )
            comment = (
                f"Cash collection queued (Cash Desk)\n"
                f"Installment {collection.installment_number}: "
                f"{collection.due_amount} {collection.currency}\n"
                f"No Paymob link was created — collect cash in Cash Desk."
            )
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type="DEAL",
                    entity_id=finance_deal_id,
                    comment=comment,
                )
            except Exception:
                logger.exception(
                    "Failed to comment cash queue on finance deal %s", finance_deal_id
                )
            raise CashCollectionQueued(collection)

        session = await self.session_service.get_or_create_reusable_session(
            workflow,
            charge_amount=plan.amount,
            charge_source=plan.source,
            amount_locked=plan.locked,
            installment_number=installment_number,
        )

        payment_url = self.session_service.build_payment_url(session.token)
        # Write link to Bitrix deal field so Bitrix can email it (no SendGrid).
        await self.bitrix.set_deal_payment_link(finance_deal_id, payment_url)
        await self.announce_payment_link(session, entity_type="DEAL", entity_id=finance_deal_id)
        workflow.last_reminder_at = datetime.now(timezone.utc)
        self.db.commit()

        logger.info(
            "Payment link created for finance deal %s — token %s...",
            finance_deal_id,
            session.token[:8],
        )
        return session

    async def _create_dev_simulated_deals(self, workflow: CustomerWorkflow) -> None:
        """Assign mock Bitrix deal IDs for local dev webhook simulation."""
        lead_id = workflow.bitrix_lead_id
        workflow.sales_deal_id = 900001 + lead_id
        workflow.finance_deal_id = 900002 + lead_id
        workflow.b2c_deal_id = 900003 + lead_id
        workflow.first_payment_at = datetime.now(timezone.utc)
        logger.info(
            "Dev simulate — mock deals for lead %s: sales=%s finance=%s b2c=%s",
            lead_id,
            workflow.sales_deal_id,
            workflow.finance_deal_id,
            workflow.b2c_deal_id,
        )

    async def _create_deals_on_first_payment(self, workflow: CustomerWorkflow) -> None:
        context = {
            "customer_email": workflow.customer_email,
            "customer_name": workflow.customer_name,
            "total_amount": str(workflow.total_amount),
            "currency": workflow.currency,
        }

        sales_deal_id = await self.bitrix.convert_lead_to_sales_deal(workflow.bitrix_lead_id, context)
        finance_deal_id = await self.bitrix.create_finance_deal(workflow.bitrix_lead_id, context)
        b2c_deal_id = await self.bitrix.create_b2c_deal(workflow.bitrix_lead_id, context)

        workflow.sales_deal_id = sales_deal_id
        workflow.finance_deal_id = finance_deal_id
        workflow.b2c_deal_id = b2c_deal_id
        workflow.first_payment_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(workflow)

        for deal_id in (sales_deal_id, finance_deal_id, b2c_deal_id):
            try:
                await self.bitrix.sync_deal_customer_details(
                    deal_id,
                    name=workflow.customer_name,
                    email=workflow.customer_email,
                    phone=workflow.customer_phone,
                )
            except Exception:
                logger.exception("Failed to sync customer details to deal %s", deal_id)

        logger.info(
            "First payment — created deals for lead %s: sales=%s finance=%s b2c=%s",
            workflow.bitrix_lead_id,
            sales_deal_id,
            finance_deal_id,
            b2c_deal_id,
        )

    async def apply_recorded_payment(
        self,
        workflow: CustomerWorkflow,
        transaction: PaymentTransaction,
        *,
        amount: Decimal,
        currency: str,
        comment_prefix: str = "Payment successful",
        skip_zoho: bool = False,
        skip_deals: bool = False,
        dev_simulate: bool = False,
    ) -> CustomerWorkflow:
        """Shared post-payment side effects for Paymob and Cash Desk collections."""
        first_payment = workflow.is_first_payment_pending
        self.threshold_service.refresh_status(workflow)
        self.db.commit()

        if first_payment and not skip_deals:
            try:
                if dev_simulate:
                    await self._create_dev_simulated_deals(workflow)
                else:
                    await self._create_deals_on_first_payment(workflow)
            except Exception:
                logger.exception(
                    "Failed to create Bitrix deals after payment for lead %s",
                    workflow.bitrix_lead_id,
                )

        comment = self._payment_success_message(
            workflow, amount, currency, prefix=comment_prefix
        )
        await self._comment_on_workflow_entities(workflow, comment)
        await self._notify_assigned_agent(
            workflow,
            subject=f"{comment_prefix} — Lead {workflow.bitrix_lead_id}",
            body=comment,
        )

        if skip_zoho or dev_simulate:
            if dev_simulate:
                logger.info("Dev simulate — skipping Zoho invoice sync")
        else:
            try:
                await self.invoice_service.sync_invoice_after_payment(workflow, transaction)
            except Exception:
                logger.exception(
                    "Failed to sync invoice after payment for lead %s",
                    workflow.bitrix_lead_id,
                )

        try:
            await self.threshold_service.apply_after_payment(
                workflow,
                latest_transaction_id=transaction.transaction_id,
            )
        except Exception:
            logger.exception(
                "Failed to apply payment threshold for lead %s",
                workflow.bitrix_lead_id,
            )

        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    async def collect_cash(
        self,
        collection_id: int,
        *,
        staff_id: int,
        amount: Decimal | None = None,
    ) -> CustomerWorkflow:
        from app.models.cash_collection import (
            STATUS_CLAIMED,
            STATUS_COLLECTED,
            STATUS_OPEN,
            CashCollection,
        )
        from app.models.staff_user import StaffUser
        from app.services.cash_collection_service import CashCollectionService

        row = self.db.get(CashCollection, collection_id)
        if not row:
            raise ValueError("Cash collection not found")
        if row.status == STATUS_COLLECTED:
            raise ValueError("Already collected")
        if row.status == STATUS_OPEN:
            raise ValueError("Claim this collection before recording cash")
        if row.status != STATUS_CLAIMED or row.claimed_by_id != staff_id:
            raise ValueError("Only the claiming employee can collect this cash")

        staff = self.db.get(StaffUser, staff_id)
        if not staff or not staff.is_active:
            raise ValueError("Staff user not found")

        collect_amount = Decimal(amount if amount is not None else row.due_amount).quantize(
            Decimal("0.01")
        )
        if collect_amount <= 0:
            raise ValueError("Collect amount must be positive")
        if collect_amount > row.due_amount:
            raise ValueError(f"Cannot collect more than due amount {row.due_amount}")

        workflow = self.db.get(CustomerWorkflow, row.workflow_id)
        if not workflow:
            raise ValueError("Workflow not found")

        txn_id = CashCollectionService.new_cash_transaction_id(row.id)
        existing = self.db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.transaction_id == txn_id)
        )
        if existing:
            raise ValueError("Duplicate cash transaction")

        workflow.amount_paid += collect_amount
        remaining = workflow.remaining_balance
        transaction = PaymentTransaction(
            workflow_id=workflow.id,
            payment_session_id=None,
            transaction_id=txn_id,
            order_id=None,
            amount=collect_amount,
            currency=row.currency or workflow.currency,
            remaining_balance=remaining,
            raw_payload=None,
            source_type="cash",
            success=True,
            pending=False,
        )
        self.db.add(transaction)

        row.collected_amount = collect_amount
        row.status = STATUS_COLLECTED
        row.collected_by_id = staff_id
        row.collected_at = datetime.now(timezone.utc)
        self.db.flush()

        course = row.course_title or CashCollectionService.course_title_from_workflow(workflow)
        comment_prefix = (
            f"Cash payment confirmed via Cash Desk\n"
            f"Collected by: {staff.name} ({staff.email})\n"
            f"Course: {course}\n"
            f"Installment {row.installment_number}"
        )
        logger.info(
            "Cash collected | lead_id=%s installment=%s amount=%s employee=%s",
            workflow.bitrix_lead_id,
            row.installment_number,
            collect_amount,
            staff.email,
        )

        return await self.apply_recorded_payment(
            workflow,
            transaction,
            amount=collect_amount,
            currency=row.currency or workflow.currency,
            comment_prefix=comment_prefix,
        )

    async def handle_paymob_webhook(
        self, data: PaymentWebhookData, *, dev_simulate: bool = False
    ) -> CustomerWorkflow | None:
        existing = self.db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.transaction_id == data.transaction_id)
        )
        if existing:
            logger.info("Duplicate transaction ignored: %s", data.transaction_id)
            return None

        session = self.db.scalar(
            select(PaymentSession).where(PaymentSession.merchant_reference == data.merchant_reference)
        )
        if not session:
            logger.warning("No payment session for merchant reference %s", data.merchant_reference)
            return None

        workflow = session.workflow
        workflow.amount_paid += data.amount
        remaining = workflow.remaining_balance

        transaction = PaymentTransaction(
            workflow_id=workflow.id,
            payment_session_id=session.id,
            transaction_id=data.transaction_id,
            order_id=data.order_id,
            amount=data.amount,
            currency=data.currency,
            remaining_balance=remaining,
            raw_payload=data.raw_payload,
        )
        apply_paymob_fields(transaction, data)
        self.db.add(transaction)
        self.session_service.mark_completed(session)
        self.db.flush()

        return await self.apply_recorded_payment(
            workflow,
            transaction,
            amount=data.amount,
            currency=data.currency,
            comment_prefix="Payment successful",
            skip_zoho=False,
            skip_deals=False,
            dev_simulate=dev_simulate,
        )

    def _payment_success_message(
        self,
        workflow: CustomerWorkflow,
        amount: Decimal,
        currency: str,
        *,
        prefix: str = "Payment successful",
    ) -> str:
        pct = workflow.payment_percentage()
        return (
            f"{prefix}\n"
            f"Amount: {amount} {currency}\n"
            f"Paid: {workflow.amount_paid} / {workflow.total_amount} {workflow.currency} "
            f"({pct:.0f}%)\n"
            f"Remaining: {workflow.remaining_balance} {workflow.currency}\n"
            f"Status: {workflow.payment_status}"
        )

    @staticmethod
    def _paymob_failure_summary(reason: str) -> str:
        lower = reason.lower()
        if "valid email" in lower or ('billing_data' in lower and '"email"' in lower):
            return "Invalid customer email — Paymob rejected the billing email."
        return reason

    async def notify_paymob_link_failure(
        self,
        workflow: CustomerWorkflow,
        *,
        reason: str,
        trigger: str = "payment link",
    ) -> None:
        """Alert the lead owner in Bitrix when Paymob refuses to create a checkout session."""
        email_on_file = (workflow.customer_email or "").strip() or "(missing or blank)"
        summary = self._paymob_failure_summary(reason)
        if "valid email" in reason.lower():
            comment = (
                f"Payment link blocked — invalid customer email\n"
                f"Paymob rejected the billing email: {email_on_file}\n"
                f"Trigger: {trigger}\n"
                f"Please correct the email on the lead and generate a new payment link."
            )
        else:
            comment = (
                f"Payment link could not be created\n"
                f"Trigger: {trigger}\n"
                f"Issue: {summary}\n"
                f"Email on file: {email_on_file}\n"
                f"Action: Fix the issue on the lead, then re-open the payment stage "
                f"or use Send payment link."
            )
        logger.warning(
            "Paymob link failure | lead_id=%s trigger=%s email=%s reason=%s",
            workflow.bitrix_lead_id,
            trigger,
            email_on_file,
            summary,
        )
        await self._comment_on_workflow_entities(workflow, comment)
        await self._notify_assigned_agent(
            workflow,
            subject=f"Payment link failed — Lead {workflow.bitrix_lead_id}",
            body=comment,
        )

    async def _comment_on_workflow_entities(self, workflow: CustomerWorkflow, comment: str) -> None:
        targets: list[tuple[str, int]] = [("LEAD", workflow.bitrix_lead_id)]
        for deal_id in (workflow.sales_deal_id, workflow.finance_deal_id, workflow.b2c_deal_id):
            if deal_id:
                targets.append(("DEAL", deal_id))

        seen: set[tuple[str, int]] = set()
        for entity_type, entity_id in targets:
            key = (entity_type, entity_id)
            if key in seen:
                continue
            seen.add(key)
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    comment=comment,
                )
                logger.info(
                    "Payment comment posted on Bitrix %s %s",
                    entity_type.lower(),
                    entity_id,
                )
            except Exception:
                logger.exception(
                    "Failed to post payment comment on Bitrix %s %s",
                    entity_type,
                    entity_id,
                )

    async def _notify_assigned_agent(
        self,
        workflow: CustomerWorkflow,
        *,
        subject: str,
        body: str,
    ) -> None:
        try:
            lead = await self.bitrix.get_lead(workflow.bitrix_lead_id)
        except Exception:
            logger.exception(
                "Could not load lead %s to notify assigned agent",
                workflow.bitrix_lead_id,
            )
            return

        owner_raw = lead.get("ASSIGNED_BY_ID") or lead.get("assignedById")
        try:
            owner_id = int(owner_raw or 0)
        except (TypeError, ValueError):
            owner_id = 0
        if owner_id <= 0:
            logger.info("No assigned agent on lead %s — skip chat/email notice", workflow.bitrix_lead_id)
            return

        chat_text = f"{subject}\n\n{body}"
        try:
            await self.bitrix.notify_user(user_id=owner_id, message=chat_text)
        except Exception:
            logger.exception("Failed Bitrix chat notice to user %s for lead %s", owner_id, workflow.bitrix_lead_id)

        agent_email = None
        agent_name = None
        try:
            user = await self.bitrix.get_user(owner_id)
        except Exception:
            logger.exception("Failed to load Bitrix user %s for agent email", owner_id)
            user = None
        if user:
            agent_email, agent_name = _bitrix_user_email_name(user)
        if not agent_email:
            logger.info(
                "Assigned agent %s has no email — chat only | lead_id=%s",
                owner_id,
                workflow.bitrix_lead_id,
            )
            return
        try:
            sent = self.email.send_agent_payment_notice(
                to_email=agent_email,
                agent_name=agent_name,
                subject=subject,
                body=body,
            )
            if sent:
                logger.info(
                    "Agent payment notice emailed | to=%s lead_id=%s",
                    agent_email,
                    workflow.bitrix_lead_id,
                )
        except Exception:
            logger.exception(
                "Failed SendGrid agent notice | to=%s lead_id=%s",
                agent_email,
                workflow.bitrix_lead_id,
            )

    async def handle_failed_payment(self, data: PaymentWebhookData) -> CustomerWorkflow | None:
        existing = self.db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.transaction_id == data.transaction_id)
        )
        if existing:
            logger.info("Duplicate failed transaction ignored: %s", data.transaction_id)
            return None

        session = self.db.scalar(
            select(PaymentSession).where(PaymentSession.merchant_reference == data.merchant_reference)
        )
        if not session:
            logger.warning("No payment session for failed merchant reference %s", data.merchant_reference)
            return None

        workflow = session.workflow
        transaction = PaymentTransaction(
            workflow_id=workflow.id,
            payment_session_id=session.id,
            transaction_id=data.transaction_id,
            order_id=data.order_id,
            amount=data.amount,
            currency=data.currency,
            remaining_balance=workflow.remaining_balance,
            status="failed",
            raw_payload=data.raw_payload,
        )
        apply_paymob_fields(transaction, data)
        transaction.success = False
        self.db.add(transaction)
        self.db.commit()

        comment = (
            f"Payment failed\n"
            f"Attempted: {data.amount} {data.currency}\n"
            f"Paid so far: {workflow.amount_paid} / {workflow.total_amount} {workflow.currency}\n"
            f"Remaining: {workflow.remaining_balance} {workflow.currency}\n"
            f"Transaction: {data.transaction_id}"
        )
        await self._comment_on_workflow_entities(workflow, comment)
        await self._notify_assigned_agent(
            workflow,
            subject=f"Payment failed — Lead {workflow.bitrix_lead_id}",
            body=comment,
        )
        self.db.refresh(workflow)
        return workflow

    async def handle_paymob_payload(self, payload: dict, signature: str | None = None) -> CustomerWorkflow | None:
        authenticate = getattr(self.paymob, "authenticate_webhook", None)
        if authenticate is not None:
            accepted = await authenticate(payload, signature)
        else:
            accepted = self.paymob.verify_webhook(payload, signature)
        if not accepted:
            raise ValueError("Invalid Paymob webhook signature")

        parse_callback = getattr(self.paymob, "parse_payment_callback", None)
        data = parse_callback(payload) if parse_callback is not None else self.paymob.parse_successful_payment(payload)
        if not data:
            return None
        if not data.success:
            return await self.handle_failed_payment(data)

        return await self.handle_paymob_webhook(data)

    async def simulate_payment(
        self,
        *,
        token: str | None = None,
        merchant_reference: str | None = None,
        amount: Decimal | None = None,
    ) -> CustomerWorkflow | None:
        session: PaymentSession | None = None
        if token:
            session = self.session_service.get_session_by_token(token)
        elif merchant_reference:
            session = self.db.scalar(
                select(PaymentSession).where(PaymentSession.merchant_reference == merchant_reference)
            )

        if not session:
            raise ValueError("Payment session not found")

        from app.integrations.paymob import build_mock_paymob_payload

        charge_amount = amount or session.charge_amount
        amount_cents = int(charge_amount * 100)
        txn_id = 100000 + session.id
        order_id = 200000 + session.id

        payload = build_mock_paymob_payload(
            transaction_id=txn_id,
            amount_cents=amount_cents,
            currency=session.currency,
            merchant_order_id=session.merchant_reference,
            order_id=order_id,
            email=session.workflow.customer_email or "customer@example.com",
        )
        data = self.paymob.parse_successful_payment(payload)
        if not data:
            return None
        dev_simulate = not self.settings.use_mock_integrations
        return await self.handle_paymob_webhook(data, dev_simulate=dev_simulate)
