"""Zoho Books integration — real stub and mock implementation."""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.integrations.base import InvoiceDocument, InvoiceReference

logger = logging.getLogger(__name__)


class MockZohoBooksClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._invoices: dict[str, InvoiceReference] = {}

    async def create_invoice(
        self,
        *,
        workflow_id: int,
        customer_name: str | None,
        customer_email: str | None,
        total_amount: Decimal,
        amount_paid: Decimal,
        currency: str,
        transaction_id: str,
    ) -> InvoiceReference:
        invoice_id = f"MOCK-INV-{workflow_id}"
        remaining = max(total_amount - amount_paid, Decimal("0.00"))
        pdf_path = self._write_mock_invoice_pdf(invoice_id, amount_paid, total_amount, remaining)

        invoice = InvoiceReference(
            invoice_id=invoice_id,
            invoice_number=f"INV-{workflow_id:05d}",
            pdf_url=None,
            pdf_path=str(pdf_path),
            amount_paid=amount_paid,
            total_amount=total_amount,
            remaining_balance=remaining,
            currency=currency,
        )
        self._invoices[invoice_id] = invoice
        logger.info("[MockZoho] Created invoice %s for workflow %s", invoice_id, workflow_id)
        return invoice

    async def apply_payment_to_invoice(
        self,
        *,
        invoice_id: str,
        amount: Decimal,
        currency: str,
        transaction_id: str,
        total_amount: Decimal,
        amount_paid: Decimal,
    ) -> InvoiceReference:
        existing = self._invoices.get(invoice_id)
        remaining = max(total_amount - amount_paid, Decimal("0.00"))
        pdf_path = self._write_mock_invoice_pdf(invoice_id, amount_paid, total_amount, remaining)

        invoice = InvoiceReference(
            invoice_id=invoice_id,
            invoice_number=existing.invoice_number if existing else invoice_id,
            pdf_url=None,
            pdf_path=str(pdf_path),
            amount_paid=amount_paid,
            total_amount=total_amount,
            remaining_balance=remaining,
            currency=currency,
        )
        self._invoices[invoice_id] = invoice
        logger.info("[MockZoho] Updated invoice %s — paid %s, remaining %s", invoice_id, amount_paid, remaining)
        return invoice

    async def get_invoice_document(self, invoice_id: str) -> InvoiceDocument:
        invoice = self._invoices.get(invoice_id)
        pdf_path = invoice.pdf_path if invoice else None
        pdf_bytes = Path(pdf_path).read_bytes() if pdf_path and Path(pdf_path).exists() else None
        return InvoiceDocument(
            invoice_id=invoice_id,
            pdf_url=invoice.pdf_url if invoice else None,
            pdf_path=pdf_path,
            pdf_bytes=pdf_bytes,
        )

    def _write_mock_invoice_pdf(
        self,
        invoice_id: str,
        amount_paid: Decimal,
        total_amount: Decimal,
        remaining: Decimal,
    ) -> Path:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        pdf_dir = Path(self.settings.storage_path) / "pdfs" / "invoices"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{invoice_id}.pdf"

        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.drawString(72, 750, f"Invoice: {invoice_id}")
        c.drawString(72, 730, f"Total: {total_amount}")
        c.drawString(72, 710, f"Paid: {amount_paid}")
        c.drawString(72, 690, f"Remaining: {remaining}")
        c.save()
        return pdf_path


class RealZohoBooksClient(MockZohoBooksClient):
    """Real Zoho Books client — OAuth + invoice APIs when configured."""

    def __init__(self, settings: Settings | None = None):
        super().__init__(settings)
        self._access_token: str | None = None

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.settings.zoho_accounts_url}/oauth/v2/token",
                params={
                    "refresh_token": self.settings.zoho_refresh_token,
                    "client_id": self.settings.zoho_client_id,
                    "client_secret": self.settings.zoho_client_secret,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            self._access_token = response.json()["access_token"]
        return self._access_token

    async def create_invoice(
        self,
        *,
        workflow_id: int,
        customer_name: str | None,
        customer_email: str | None,
        total_amount: Decimal,
        amount_paid: Decimal,
        currency: str,
        transaction_id: str,
    ) -> InvoiceReference:
        if self.settings.use_mock_integrations or not self.settings.zoho_refresh_token:
            return await super().create_invoice(
                workflow_id=workflow_id,
                customer_name=customer_name,
                customer_email=customer_email,
                total_amount=total_amount,
                amount_paid=amount_paid,
                currency=currency,
                transaction_id=transaction_id,
            )
        raise NotImplementedError("Real Zoho invoice creation — configure and implement when credentials available")

    async def apply_payment_to_invoice(
        self,
        *,
        invoice_id: str,
        amount: Decimal,
        currency: str,
        transaction_id: str,
        total_amount: Decimal,
        amount_paid: Decimal,
    ) -> InvoiceReference:
        if self.settings.use_mock_integrations or not self.settings.zoho_refresh_token:
            return await super().apply_payment_to_invoice(
                invoice_id=invoice_id,
                amount=amount,
                currency=currency,
                transaction_id=transaction_id,
                total_amount=total_amount,
                amount_paid=amount_paid,
            )
        raise NotImplementedError("Real Zoho payment application — configure and implement when credentials available")
