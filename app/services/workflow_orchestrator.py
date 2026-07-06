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
from app.services.invoice_service import InvoiceService
from app.services.paymob_mapper import apply_paymob_fields
from app.services.payment_session_service import PaymentSessionService

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

    def get_workflow_by_finance_deal(self, finance_deal_id: int) -> CustomerWorkflow | None:
        return self.db.scalar(
            select(CustomerWorkflow).where(CustomerWorkflow.finance_deal_id == finance_deal_id)
        )

    async def sync_workflow_from_lead(self, workflow: CustomerWorkflow) -> CustomerWorkflow:
        lead = await self.bitrix.get_lead(workflow.bitrix_lead_id)
        workflow.total_amount = self.bitrix.extract_lead_amount(lead)
        email, name = self.bitrix.extract_customer_details(lead)
        workflow.customer_email = email
        workflow.customer_name = name
        workflow.currency = lead.get("CURRENCY_ID") or self.settings.default_currency
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    async def initiate_payment_from_lead(self, lead_id: int) -> PaymentSession:
        workflow = self.get_or_create_workflow(lead_id)
        await self.sync_workflow_from_lead(workflow)

        source_type, source_id = PaymentSessionService.source_lead(lead_id)
        session = await self.session_service.create_session(
            workflow, source_type=source_type, source_id=source_id
        )

        if workflow.customer_email:
            payment_url = self.session_service.build_payment_url(session.token)
            self.email.send_payment_request(
                to_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
            )

        logger.info("Payment link created for lead %s — token %s...", lead_id, session.token[:8])
        return session

    async def initiate_payment_from_finance_deal(self, finance_deal_id: int) -> PaymentSession:
        workflow = self.get_workflow_by_finance_deal(finance_deal_id)
        if not workflow:
            raise ValueError(f"No workflow found for finance deal {finance_deal_id}")

        if workflow.remaining_balance <= 0 and workflow.amount_paid >= workflow.total_amount:
            raise ValueError(f"Finance deal {finance_deal_id} has no remaining balance")

        source_type, source_id = PaymentSessionService.source_finance_deal(finance_deal_id)
        session = await self.session_service.create_session(
            workflow, source_type=source_type, source_id=source_id
        )

        if workflow.customer_email:
            payment_url = self.session_service.build_payment_url(session.token)
            self.email.send_payment_request(
                to_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
            )

        logger.info(
            "Payment link created for finance deal %s — token %s...",
            finance_deal_id,
            session.token[:8],
        )
        return session

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

        logger.info(
            "First payment — created deals for lead %s: sales=%s finance=%s b2c=%s",
            workflow.bitrix_lead_id,
            sales_deal_id,
            finance_deal_id,
            b2c_deal_id,
        )

    async def handle_paymob_webhook(self, data: PaymentWebhookData) -> CustomerWorkflow | None:
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

        if workflow.is_first_payment_pending:
            await self._create_deals_on_first_payment(workflow)

        await self.invoice_service.sync_invoice_after_payment(workflow, transaction)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    async def handle_paymob_payload(self, payload: dict, signature: str | None = None) -> CustomerWorkflow | None:
        if not self.paymob.verify_webhook(payload, signature):
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
        return await self.handle_paymob_payload(payload)
