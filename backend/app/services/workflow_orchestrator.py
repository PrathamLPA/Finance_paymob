"""Central workflow orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.base import PaymentWebhookData
from app.integrations.factory import get_bitrix_client, get_email_client, get_paymob_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import SOURCE_FINANCE_DEAL, SOURCE_LEAD, PaymentSession
from app.models.payment_transaction import PaymentTransaction
from app.services.estimate_price_gate import (
    evaluate_price_gate,
    product_rows_for_estimate,
)
from app.services.invoice_service import InvoiceService
from app.services.paymob_mapper import apply_paymob_fields
from app.services.payment_session_service import PaymentSessionService
from app.services.payment_threshold_service import PaymentThresholdService

logger = logging.getLogger(__name__)


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
        """Comment the link on the CRM entity once per session, unless forced."""
        if session.link_commented_at and not force:
            return False

        payment_url = self.session_service.build_payment_url(session.token)
        workflow = session.workflow
        minimum = workflow.minimum_due(self.settings.payment_required_percent)
        comment = (
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
            "Payment link commented on Bitrix %s %s", entity_type.lower(), entity_id
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
        """Block underpriced leads; create a Bitrix Estimate when prices are valid."""
        if not self.settings.bitrix_price_gate_enabled:
            return

        lead_id = workflow.bitrix_lead_id
        lead = lead or await self.bitrix.get_lead(lead_id)
        rows = await self.bitrix.list_product_rows(owner_type="L", owner_id=lead_id)

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
            if price is not None:
                catalog_prices[product_id] = price

        gate = evaluate_price_gate(rows, catalog_prices)
        currency = workflow.currency or self.settings.default_currency
        comment = gate.summary_comment(currency=currency, amount_paid=workflow.amount_paid)

        if not gate.ok:
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type="LEAD",
                    entity_id=lead_id,
                    comment=comment,
                )
            except Exception:
                logger.exception(
                    "Failed to post price-gate block comment on lead %s", lead_id
                )
            logger.warning(
                "Price gate blocked payment link | lead_id=%s reason=%s",
                lead_id,
                gate.reason,
            )
            raise ValueError(gate.reason)

        # Prefer product-derived total when the gate produced one.
        if gate.total_payable > 0:
            workflow.total_amount = gate.total_payable
            self.db.commit()
            self.db.refresh(workflow)

        if workflow.bitrix_estimate_id:
            logger.info(
                "Reusing Bitrix estimate %s for lead %s",
                workflow.bitrix_estimate_id,
                lead_id,
            )
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type="LEAD",
                    entity_id=lead_id,
                    comment=(
                        f"{comment}\n\n"
                        f"Estimate already exists: #{workflow.bitrix_estimate_id}. "
                        "Payment link will be sent."
                    ),
                )
            except Exception:
                logger.exception(
                    "Failed to post estimate reuse comment on lead %s", lead_id
                )
            return

        contact_raw = lead.get("CONTACT_ID") or lead.get("contactId")
        try:
            contact_id = int(contact_raw) if contact_raw not in (None, "", "0") else None
        except (TypeError, ValueError):
            contact_id = None

        title = str(lead.get("TITLE") or lead.get("title") or f"Estimate for lead {lead_id}")
        estimate_id = await self.bitrix.create_estimate(
            lead_id=lead_id,
            title=f"Estimate — {title}",
            currency=currency,
            opportunity=gate.total_payable,
            tax_value=gate.tax_total,
            contact_id=contact_id,
            product_rows=product_rows_for_estimate(gate.lines),
            comments=comment,
        )
        workflow.bitrix_estimate_id = estimate_id
        self.db.commit()
        self.db.refresh(workflow)

        try:
            await self.bitrix.add_timeline_comment(
                entity_type="LEAD",
                entity_id=lead_id,
                comment=(
                    f"{comment}\n\n"
                    f"Estimate #{estimate_id} created. Payment link will be sent."
                ),
            )
        except Exception:
            logger.exception(
                "Failed to post estimate-created comment on lead %s", lead_id
            )

        logger.info(
            "Price gate passed | lead_id=%s estimate_id=%s total=%s %s",
            lead_id,
            estimate_id,
            gate.total_payable,
            currency,
        )

    async def initiate_payment_from_lead(
        self,
        lead_id: int,
        *,
        customer_email: str | None = None,
        customer_name: str | None = None,
        total_amount: Decimal | None = None,
        lead_data: dict | None = None,
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
            await self._enforce_price_gate_and_create_estimate(
                workflow, lead=lead_data
            )

        if workflow.total_amount <= 0:
            raise ValueError(
                f"Lead {lead_id} has no payment amount — set OPPORTUNITY "
                f"(or BITRIX_FIELD_LEAD_AMOUNT) in Bitrix before requesting payment"
            )

        session = await self.session_service.get_or_create_reusable_session(workflow)
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

        logger.info("Payment link created for lead %s — token %s...", lead_id, session.token[:8])
        return session

    async def initiate_payment_from_finance_deal(self, finance_deal_id: int) -> PaymentSession:
        workflow = self.get_workflow_by_finance_deal(finance_deal_id)
        if not workflow:
            raise ValueError(f"No workflow found for finance deal {finance_deal_id}")

        if workflow.remaining_balance <= 0 and workflow.amount_paid >= workflow.total_amount:
            raise ValueError(f"Finance deal {finance_deal_id} has no remaining balance")

        session = await self.session_service.get_or_create_reusable_session(workflow)

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

        # Money is recorded; tell Bitrix before anything else can fail.
        first_payment = workflow.is_first_payment_pending
        self.threshold_service.refresh_status(workflow)
        self.db.commit()
        await self._comment_payment_received(workflow, data.amount, data.currency)

        if first_payment:
            try:
                if dev_simulate:
                    await self._create_dev_simulated_deals(workflow)
                else:
                    await self._create_deals_on_first_payment(workflow)
            except Exception:
                logger.exception(
                    "Failed to create Bitrix deals after first payment for lead %s",
                    workflow.bitrix_lead_id,
                )

        if dev_simulate:
            logger.info("Dev simulate — skipping Zoho invoice sync")
        else:
            try:
                await self.invoice_service.sync_invoice_after_payment(workflow, transaction)
            except Exception:
                logger.exception(
                    "Failed to sync invoice after payment for lead %s", workflow.bitrix_lead_id
                )

        try:
            await self.threshold_service.apply_after_payment(
                workflow,
                latest_transaction_id=transaction.transaction_id,
            )
        except Exception:
            logger.exception(
                "Failed to apply payment threshold for lead %s", workflow.bitrix_lead_id
            )

        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    async def _comment_payment_received(
        self,
        workflow: CustomerWorkflow,
        amount: Decimal,
        currency: str,
    ) -> None:
        """Notify Bitrix with a timeline comment after a successful payment."""
        status = workflow.payment_status
        pct = workflow.payment_percentage()
        comment = (
            f"Payment received: {amount} {currency}\n"
            f"Paid: {workflow.amount_paid} / {workflow.total_amount} {workflow.currency} "
            f"({pct:.0f}%)\n"
            f"Remaining: {workflow.remaining_balance} {workflow.currency}\n"
            f"Status: {status}"
        )

        targets: list[tuple[str, int]] = [("LEAD", workflow.bitrix_lead_id)]
        if workflow.finance_deal_id:
            targets.append(("DEAL", workflow.finance_deal_id))

        for entity_type, entity_id in targets:
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    comment=comment,
                )
                logger.info(
                    "Payment received comment posted on Bitrix %s %s",
                    entity_type.lower(),
                    entity_id,
                )
            except Exception:
                logger.exception(
                    "Failed to post payment comment on Bitrix %s %s",
                    entity_type,
                    entity_id,
                )

    async def handle_paymob_payload(self, payload: dict, signature: str | None = None) -> CustomerWorkflow | None:
        authenticate = getattr(self.paymob, "authenticate_webhook", None)
        if authenticate is not None:
            accepted = await authenticate(payload, signature)
        else:
            accepted = self.paymob.verify_webhook(payload, signature)
        if not accepted:
            raise ValueError("Invalid Paymob webhook signature")

        data = self.paymob.parse_successful_payment(payload)
        if not data:
            return None

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
