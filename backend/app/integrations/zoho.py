"""Zoho Books integration — real API and mock implementation."""

from __future__ import annotations

import logging
from datetime import date
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
    """Zoho Books OAuth + invoices + customer payments."""

    def __init__(self, settings: Settings | None = None):
        super().__init__(settings)
        self._access_token: str | None = None
        self._customer_ids: dict[str, str] = {}

    def _org_params(self) -> dict[str, str]:
        if not self.settings.zoho_organization_id:
            raise RuntimeError("ZOHO_ORGANIZATION_ID is not configured")
        return {"organization_id": self.settings.zoho_organization_id}

    async def _get_access_token(self, *, force_refresh: bool = False) -> str:
        if self._access_token and not force_refresh:
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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        token = await self._get_access_token()
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        if accept:
            headers["Accept"] = accept
        query = {**(params or {}), **self._org_params()}
        url = f"{self.settings.zoho_books_api_url.rstrip('/')}/{path.lstrip('/')}"

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.request(method, url, headers=headers, params=query, json=json)
            if response.status_code == 401:
                token = await self._get_access_token(force_refresh=True)
                headers["Authorization"] = f"Zoho-oauthtoken {token}"
                response = await client.request(method, url, headers=headers, params=query, json=json)
            response.raise_for_status()
            return response

    async def _find_or_create_customer(
        self,
        *,
        customer_name: str | None,
        customer_email: str | None,
    ) -> str:
        email_key = (customer_email or "").strip().lower()
        if email_key and email_key in self._customer_ids:
            return self._customer_ids[email_key]

        if email_key:
            response = await self._request("GET", "/contacts", params={"email": email_key})
            contacts = response.json().get("contacts") or []
            if contacts:
                contact_id = str(contacts[0]["contact_id"])
                self._customer_ids[email_key] = contact_id
                return contact_id

        name = (customer_name or customer_email or "Customer").strip()
        payload = {
            "contact_name": name,
            "contact_type": "customer",
        }
        if customer_email:
            payload["email"] = customer_email

        response = await self._request("POST", "/contacts", json=payload)
        contact = response.json().get("contact") or {}
        contact_id = str(contact["contact_id"])
        if email_key:
            self._customer_ids[email_key] = contact_id
        return contact_id

    def _line_items(self, *, total_amount: Decimal, currency: str) -> list[dict]:
        item: dict = {
            "name": "Course / Training Fee",
            "description": f"Total fee ({currency})",
            "rate": float(total_amount),
            "quantity": 1,
        }
        if self.settings.zoho_default_item_id:
            item["item_id"] = self.settings.zoho_default_item_id
        return [item]

    async def _record_payment(
        self,
        *,
        customer_id: str,
        invoice_id: str,
        amount: Decimal,
        transaction_id: str,
    ) -> None:
        if amount <= 0:
            return
        payload = {
            "customer_id": customer_id,
            "payment_mode": "others",
            "amount": float(amount),
            "date": date.today().isoformat(),
            "reference_number": transaction_id[:50],
            "invoices": [{"invoice_id": invoice_id, "amount_applied": float(amount)}],
        }
        await self._request("POST", "/customerpayments", json=payload)

    async def _download_invoice_pdf(self, invoice_id: str) -> Path | None:
        try:
            response = await self._request(
                "GET",
                f"/invoices/{invoice_id}",
                params={"accept": "pdf"},
                accept="application/pdf",
            )
            pdf_dir = Path(self.settings.storage_path) / "pdfs" / "invoices"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_dir / f"zoho_{invoice_id}.pdf"
            pdf_path.write_bytes(response.content)
            return pdf_path
        except Exception:
            logger.exception("Failed to download Zoho invoice PDF %s", invoice_id)
            return None

    def _to_reference(
        self,
        *,
        invoice_id: str,
        invoice_number: str,
        total_amount: Decimal,
        amount_paid: Decimal,
        currency: str,
        pdf_path: Path | None,
        pdf_url: str | None = None,
    ) -> InvoiceReference:
        return InvoiceReference(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            pdf_url=pdf_url,
            pdf_path=str(pdf_path) if pdf_path else None,
            amount_paid=amount_paid,
            total_amount=total_amount,
            remaining_balance=max(total_amount - amount_paid, Decimal("0.00")),
            currency=currency,
        )

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

        customer_id = await self._find_or_create_customer(
            customer_name=customer_name,
            customer_email=customer_email,
        )
        payload = {
            "customer_id": customer_id,
            "currency_code": currency,
            "line_items": self._line_items(total_amount=total_amount, currency=currency),
            "reference_number": f"WF-{workflow_id}-{transaction_id}"[:50],
        }
        response = await self._request("POST", "/invoices", json=payload)
        invoice = response.json().get("invoice") or {}
        invoice_id = str(invoice["invoice_id"])
        invoice_number = str(invoice.get("invoice_number") or invoice_id)

        await self._record_payment(
            customer_id=customer_id,
            invoice_id=invoice_id,
            amount=amount_paid,
            transaction_id=transaction_id,
        )
        pdf_path = await self._download_invoice_pdf(invoice_id)
        pdf_url = invoice.get("invoice_url")
        ref = self._to_reference(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            total_amount=total_amount,
            amount_paid=amount_paid,
            currency=currency,
            pdf_path=pdf_path,
            pdf_url=pdf_url,
        )
        self._invoices[invoice_id] = ref
        # stash customer id on reference via side map for invoice_service
        self._customer_ids[f"invoice:{invoice_id}"] = customer_id
        logger.info("Zoho invoice %s created for workflow %s", invoice_id, workflow_id)
        return ref

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

        customer_id = self._customer_ids.get(f"invoice:{invoice_id}")
        if not customer_id:
            inv = await self._request("GET", f"/invoices/{invoice_id}")
            customer_id = str((inv.json().get("invoice") or {}).get("customer_id") or "")
            if customer_id:
                self._customer_ids[f"invoice:{invoice_id}"] = customer_id

        if not customer_id:
            raise RuntimeError(f"Could not resolve Zoho customer for invoice {invoice_id}")

        await self._record_payment(
            customer_id=customer_id,
            invoice_id=invoice_id,
            amount=amount,
            transaction_id=transaction_id,
        )
        inv = await self._request("GET", f"/invoices/{invoice_id}")
        invoice = inv.json().get("invoice") or {}
        pdf_path = await self._download_invoice_pdf(invoice_id)
        ref = self._to_reference(
            invoice_id=invoice_id,
            invoice_number=str(invoice.get("invoice_number") or invoice_id),
            total_amount=total_amount,
            amount_paid=amount_paid,
            currency=currency,
            pdf_path=pdf_path,
            pdf_url=invoice.get("invoice_url"),
        )
        self._invoices[invoice_id] = ref
        logger.info("Zoho payment applied to invoice %s — amount %s", invoice_id, amount)
        return ref

    async def get_invoice_document(self, invoice_id: str) -> InvoiceDocument:
        if self.settings.use_mock_integrations or not self.settings.zoho_refresh_token:
            return await super().get_invoice_document(invoice_id)

        cached = self._invoices.get(invoice_id)
        pdf_path = Path(cached.pdf_path) if cached and cached.pdf_path else await self._download_invoice_pdf(invoice_id)
        pdf_bytes = pdf_path.read_bytes() if pdf_path and pdf_path.exists() else None
        return InvoiceDocument(
            invoice_id=invoice_id,
            pdf_url=cached.pdf_url if cached else None,
            pdf_path=str(pdf_path) if pdf_path else None,
            pdf_bytes=pdf_bytes,
        )
