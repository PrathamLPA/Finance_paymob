"""Invoice sync — Zoho + Bitrix attachment + customer email."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.base import InvoiceReference, PaymentSummary
from app.integrations.factory import get_bitrix_client, get_email_client, get_zoho_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_transaction import PaymentTransaction

logger = logging.getLogger(__name__)


class InvoiceService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.bitrix = get_bitrix_client(self.settings)
        self.zoho = get_zoho_client(self.settings)
        self.email = get_email_client(self.settings)

    async def sync_invoice_after_payment(
        self,
        workflow: CustomerWorkflow,
        transaction: PaymentTransaction,
    ) -> InvoiceReference:
        if workflow.zoho_invoice_id:
            if workflow.zoho_customer_id:
                customer_map = getattr(self.zoho, "_customer_ids", None)
                if isinstance(customer_map, dict):
                    customer_map[f"invoice:{workflow.zoho_invoice_id}"] = workflow.zoho_customer_id
            invoice = await self.zoho.apply_payment_to_invoice(
                invoice_id=workflow.zoho_invoice_id,
                amount=transaction.amount,
                currency=transaction.currency,
                transaction_id=transaction.transaction_id,
                total_amount=workflow.total_amount,
                amount_paid=workflow.amount_paid,
            )
        else:
            invoice = await self.zoho.create_invoice(
                workflow_id=workflow.id,
                customer_name=workflow.customer_name,
                customer_email=workflow.customer_email,
                total_amount=workflow.total_amount,
                amount_paid=workflow.amount_paid,
                currency=workflow.currency,
                transaction_id=transaction.transaction_id,
            )
            workflow.zoho_invoice_id = invoice.invoice_id
            customer_map = getattr(self.zoho, "_customer_ids", {})
            zoho_customer = customer_map.get(f"invoice:{invoice.invoice_id}")
            if zoho_customer:
                workflow.zoho_customer_id = zoho_customer
            self.db.commit()

        document = await self.zoho.get_invoice_document(invoice.invoice_id)
        if document.pdf_path:
            invoice = InvoiceReference(
                invoice_id=invoice.invoice_id,
                invoice_number=invoice.invoice_number,
                pdf_url=invoice.pdf_url,
                pdf_path=document.pdf_path,
                amount_paid=invoice.amount_paid,
                total_amount=invoice.total_amount,
                remaining_balance=invoice.remaining_balance,
                currency=invoice.currency,
            )

        await self._attach_to_all_deals(workflow, invoice, transaction)
        self._email_invoice_to_customer(workflow, invoice, document.pdf_path)
        return invoice

    async def _attach_to_all_deals(
        self,
        workflow: CustomerWorkflow,
        invoice: InvoiceReference,
        transaction: PaymentTransaction,
    ) -> None:
        summary = PaymentSummary(
            total_amount=workflow.total_amount,
            amount_paid=workflow.amount_paid,
            remaining_balance=workflow.remaining_balance,
            currency=workflow.currency,
            latest_transaction_id=transaction.transaction_id,
            payment_percentage=workflow.payment_percentage(),
            payment_status=workflow.payment_status,
        )

        deal_ids = [workflow.sales_deal_id, workflow.finance_deal_id, workflow.b2c_deal_id]
        for deal_id in deal_ids:
            if deal_id:
                try:
                    await self.bitrix.attach_invoice_reference(deal_id, invoice)
                    await self.bitrix.update_deal_payment_summary(deal_id, summary)
                except Exception:
                    logger.exception("Failed to attach invoice to deal %s", deal_id)

    def _email_invoice_to_customer(
        self,
        workflow: CustomerWorkflow,
        invoice: InvoiceReference,
        document_path: str | None,
    ) -> None:
        if not workflow.customer_email:
            logger.warning("No customer email for workflow %s — skipping invoice email", workflow.id)
            return

        self.email.send_invoice(
            to_email=workflow.customer_email,
            customer_name=workflow.customer_name,
            invoice_reference=invoice,
            document_path=document_path,
        )
