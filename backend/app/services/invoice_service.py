"""Invoice sync — Zoho + Bitrix attachment + customer email."""

from __future__ import annotations

import logging
from pathlib import Path

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
        created_new = False
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
            created_new = True

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

        await self._publish_invoice_to_bitrix(
            workflow, invoice, transaction, created_new=created_new
        )
        self._email_invoice_to_customer(workflow, invoice, document.pdf_path)
        return invoice

    async def retrigger_invoice_delivery(
        self,
        workflow: CustomerWorkflow,
        transaction: PaymentTransaction,
    ) -> dict:
        """Create Zoho invoice if missing, then (re)post to Bitrix and email customer.

        When an invoice already exists, payment is not applied again in Zoho — only
        Bitrix timeline/fields and customer email are re-sent.
        """
        steps: dict[str, str] = {
            "zoho": "pending",
            "bitrix": "pending",
            "email": "pending",
        }
        created_new = False
        invoice: InvoiceReference | None = None
        document_path: str | None = None

        try:
            if workflow.zoho_invoice_id:
                if workflow.zoho_customer_id:
                    customer_map = getattr(self.zoho, "_customer_ids", None)
                    if isinstance(customer_map, dict):
                        customer_map[f"invoice:{workflow.zoho_invoice_id}"] = (
                            workflow.zoho_customer_id
                        )
                document = await self.zoho.get_invoice_document(workflow.zoho_invoice_id)
                document_path = document.pdf_path
                invoice_number = workflow.zoho_invoice_id
                cached = getattr(self.zoho, "_invoices", {}).get(workflow.zoho_invoice_id)
                if cached and getattr(cached, "invoice_number", None):
                    invoice_number = cached.invoice_number
                invoice = InvoiceReference(
                    invoice_id=workflow.zoho_invoice_id,
                    invoice_number=str(invoice_number),
                    pdf_url=document.pdf_url,
                    pdf_path=document.pdf_path,
                    amount_paid=workflow.amount_paid,
                    total_amount=workflow.total_amount,
                    remaining_balance=workflow.remaining_balance,
                    currency=workflow.currency,
                )
                steps["zoho"] = "already_exists"
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
                created_new = True
                document = await self.zoho.get_invoice_document(invoice.invoice_id)
                document_path = document.pdf_path
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
                steps["zoho"] = "created"
        except Exception as exc:
            logger.exception(
                "Invoice retrigger Zoho failed | workflow=%s lead=%s",
                workflow.id,
                workflow.bitrix_lead_id,
            )
            steps["zoho"] = f"error: {exc}"
            steps["bitrix"] = "skipped"
            steps["email"] = "skipped"
            return {
                "ok": False,
                "workflow_id": workflow.id,
                "bitrix_lead_id": workflow.bitrix_lead_id,
                "transaction_id": transaction.transaction_id,
                "zoho_invoice_id": workflow.zoho_invoice_id,
                "invoice_number": None,
                "created_new": False,
                "steps": steps,
                "detail": str(exc),
            }

        assert invoice is not None

        try:
            await self._publish_invoice_to_bitrix(
                workflow, invoice, transaction, created_new=created_new
            )
            steps["bitrix"] = "ok"
        except Exception as exc:
            logger.exception(
                "Invoice retrigger Bitrix failed | workflow=%s lead=%s",
                workflow.id,
                workflow.bitrix_lead_id,
            )
            steps["bitrix"] = f"error: {exc}"

        try:
            if not workflow.customer_email:
                steps["email"] = "skipped_no_email"
            else:
                self._email_invoice_to_customer(workflow, invoice, document_path)
                steps["email"] = "ok"
        except Exception as exc:
            logger.exception(
                "Invoice retrigger email failed | workflow=%s lead=%s",
                workflow.id,
                workflow.bitrix_lead_id,
            )
            steps["email"] = f"error: {exc}"

        ok = steps["zoho"] in ("created", "already_exists") and not str(
            steps["bitrix"]
        ).startswith("error")
        return {
            "ok": ok,
            "workflow_id": workflow.id,
            "bitrix_lead_id": workflow.bitrix_lead_id,
            "transaction_id": transaction.transaction_id,
            "zoho_invoice_id": workflow.zoho_invoice_id,
            "invoice_number": invoice.invoice_number,
            "created_new": created_new,
            "steps": steps,
            "detail": None,
        }

    def _invoice_pdf_files(self, invoice: InvoiceReference) -> list[tuple[str, bytes]] | None:
        if not invoice.pdf_path:
            return None
        path = Path(invoice.pdf_path)
        if not path.is_file():
            logger.warning(
                "Zoho invoice PDF missing on disk | invoice=%s path=%s",
                invoice.invoice_id,
                invoice.pdf_path,
            )
            return None
        safe_number = "".join(
            ch if ch.isalnum() or ch in "-_" else "_" for ch in (invoice.invoice_number or "invoice")
        )
        return [(f"Invoice_{safe_number}.pdf", path.read_bytes())]

    async def _publish_invoice_to_bitrix(
        self,
        workflow: CustomerWorkflow,
        invoice: InvoiceReference,
        transaction: PaymentTransaction,
        *,
        created_new: bool,
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
            if not deal_id:
                continue
            try:
                await self.bitrix.attach_invoice_reference(deal_id, invoice)
                await self.bitrix.update_deal_payment_summary(deal_id, summary)
                logger.info(
                    "Invoice fields updated on Bitrix deal %s | invoice=%s",
                    deal_id,
                    invoice.invoice_number,
                )
            except Exception:
                logger.exception("Failed to attach invoice to deal %s", deal_id)

        action = "created" if created_new else "updated"
        lines = [
            f"Zoho invoice {action}: {invoice.invoice_number}",
            f"Paid this payment: {transaction.amount} {transaction.currency}",
            f"Total paid: {invoice.amount_paid} / {invoice.total_amount} {invoice.currency}",
            f"Remaining: {invoice.remaining_balance} {invoice.currency}",
        ]
        if invoice.pdf_url:
            lines.append(f"Invoice link: {invoice.pdf_url}")
        comment = "\n".join(lines)
        files = self._invoice_pdf_files(invoice)

        targets: list[tuple[str, int]] = [("LEAD", workflow.bitrix_lead_id)]
        if workflow.bitrix_estimate_id:
            targets.append(("quote", int(workflow.bitrix_estimate_id)))
        for deal_id in deal_ids:
            if deal_id:
                targets.append(("DEAL", int(deal_id)))

        seen: set[tuple[str, int]] = set()
        for entity_type, entity_id in targets:
            key = (entity_type.upper(), entity_id)
            if key in seen:
                continue
            seen.add(key)
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    comment=comment,
                    files=files,
                )
                logger.info(
                    "Invoice timeline comment posted on Bitrix %s %s | invoice=%s files=%s",
                    entity_type.lower(),
                    entity_id,
                    invoice.invoice_number,
                    len(files or []),
                )
            except Exception:
                logger.exception(
                    "Failed invoice timeline comment on Bitrix %s %s",
                    entity_type,
                    entity_id,
                )

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
