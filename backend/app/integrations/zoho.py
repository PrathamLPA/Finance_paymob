"""Zoho Books integration — real API and mock implementation.

Auth and invoice creation follow Zoho Books API v3:
https://www.zoho.com/books/api/v3/oauth/
https://www.zoho.com/books/api/v3/invoices/#create-an-invoice
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings
from app.integrations.base import InvoiceDocument, InvoiceReference

logger = logging.getLogger(__name__)

DEFAULT_ZOHO_SCOPES = (
    "ZohoBooks.contacts.CREATE,ZohoBooks.contacts.READ,"
    "ZohoBooks.invoices.CREATE,ZohoBooks.invoices.READ,ZohoBooks.invoices.UPDATE,"
    "ZohoBooks.customerpayments.CREATE,ZohoBooks.settings.READ"
)


class ZohoBooksApiError(RuntimeError):
    """Zoho Books REST error with API code/message when available."""

    def __init__(self, *, status_code: int, code: str, message: str, body: str = ""):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.body = body
        super().__init__(f"Zoho Books API {status_code} [{code}]: {message}")


class MockZohoBooksClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._invoices: dict[str, InvoiceReference] = {}
        self._customer_ids: dict[str, str] = {}

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
        self._customer_ids[f"invoice:{invoice_id}"] = f"MOCK-CUST-{workflow_id}"
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

    async def test_connection(self) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "mock",
            "message": "Using MockZohoBooksClient (set ZOHO_* and USE_MOCK_INTEGRATIONS=false for live)",
        }

    async def list_organizations(self) -> list[dict[str, Any]]:
        return [{"organization_id": "mock-org", "name": "Mock Organization"}]

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
    """Zoho Books OAuth + contacts + invoices + customer payments."""

    def __init__(self, settings: Settings | None = None):
        super().__init__(settings)
        self._access_token: str | None = None

    def _org_params(self) -> dict[str, str]:
        if not self.settings.zoho_organization_id:
            raise RuntimeError("ZOHO_ORGANIZATION_ID is not configured")
        return {"organization_id": self.settings.zoho_organization_id}

    def _scopes(self) -> str:
        return (self.settings.zoho_oauth_scopes or DEFAULT_ZOHO_SCOPES).strip()

    def build_authorization_url(self, *, state: str = "zoho-books-connect") -> str:
        """Step 2 of Zoho OAuth — open this URL to approve the app and get a grant code."""
        if not self.settings.zoho_client_id:
            raise RuntimeError("ZOHO_CLIENT_ID is required")
        redirect = (self.settings.zoho_oauth_redirect_uri or "").strip()
        if not redirect:
            raise RuntimeError(
                "ZOHO_OAUTH_REDIRECT_URI is required (must match the URL registered in Zoho API Console)"
            )
        params = {
            "scope": self._scopes(),
            "client_id": self.settings.zoho_client_id,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "redirect_uri": redirect,
            "state": state,
        }
        return f"{self.settings.zoho_accounts_url.rstrip('/')}/oauth/v2/auth?{urlencode(params)}"

    async def exchange_authorization_code(self, code: str) -> dict[str, Any]:
        """Step 3 — exchange grant code for access + refresh tokens."""
        if not self.settings.zoho_client_id or not self.settings.zoho_client_secret:
            raise RuntimeError("ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET are required")
        redirect = (self.settings.zoho_oauth_redirect_uri or "").strip()
        if not redirect:
            raise RuntimeError("ZOHO_OAUTH_REDIRECT_URI is required")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.settings.zoho_accounts_url.rstrip('/')}/oauth/v2/token",
                params={
                    "grant_type": "authorization_code",
                    "client_id": self.settings.zoho_client_id,
                    "client_secret": self.settings.zoho_client_secret,
                    "redirect_uri": redirect,
                    "code": code.strip(),
                },
            )
        data = response.json() if response.content else {}
        if response.is_error or data.get("error"):
            raise ZohoBooksApiError(
                status_code=response.status_code,
                code=str(data.get("error") or "token_exchange_failed"),
                message=str(data.get("error_description") or data.get("message") or response.text[:300]),
                body=response.text[:500],
            )
        refresh = data.get("refresh_token")
        if not refresh:
            raise ZohoBooksApiError(
                status_code=response.status_code,
                code="missing_refresh_token",
                message=(
                    "Zoho did not return a refresh_token. Re-authorize with access_type=offline "
                    "and prompt=consent, or generate a Self Client token in Zoho API Console."
                ),
                body=str(data)[:500],
            )
        self._access_token = data.get("access_token")
        logger.info("Zoho OAuth code exchanged — refresh_token received")
        return {
            "access_token": data.get("access_token"),
            "refresh_token": refresh,
            "expires_in": data.get("expires_in"),
            "api_domain": data.get("api_domain"),
            "token_type": data.get("token_type"),
        }

    async def _get_access_token(self, *, force_refresh: bool = False) -> str:
        if self._access_token and not force_refresh:
            return self._access_token
        if not self.settings.zoho_refresh_token:
            raise RuntimeError("ZOHO_REFRESH_TOKEN is not configured")
        if not self.settings.zoho_client_id or not self.settings.zoho_client_secret:
            raise RuntimeError("ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET are required")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.settings.zoho_accounts_url.rstrip('/')}/oauth/v2/token",
                params={
                    "refresh_token": self.settings.zoho_refresh_token,
                    "client_id": self.settings.zoho_client_id,
                    "client_secret": self.settings.zoho_client_secret,
                    "grant_type": "refresh_token",
                },
            )
        data = response.json() if response.content else {}
        if response.is_error or data.get("error"):
            raise ZohoBooksApiError(
                status_code=response.status_code,
                code=str(data.get("error") or "refresh_failed"),
                message=str(data.get("error_description") or data.get("message") or response.text[:300]),
                body=response.text[:500],
            )
        token = data.get("access_token")
        if not token:
            raise ZohoBooksApiError(
                status_code=response.status_code,
                code="missing_access_token",
                message="Zoho refresh response had no access_token",
                body=str(data)[:500],
            )
        self._access_token = str(token)
        return self._access_token

    @staticmethod
    def _raise_for_zoho_response(response: httpx.Response) -> None:
        if not response.is_error:
            # Zoho sometimes returns 200 with code != 0
            try:
                payload = response.json()
            except ValueError:
                return
            code = payload.get("code")
            if code not in (None, 0, "0"):
                raise ZohoBooksApiError(
                    status_code=response.status_code,
                    code=str(code),
                    message=str(payload.get("message") or "Zoho Books API error"),
                    body=response.text[:500],
                )
            return

        code = "http_error"
        message = response.text[:300]
        try:
            payload = response.json()
            code = str(payload.get("code") or payload.get("error") or code)
            message = str(payload.get("message") or payload.get("error_description") or message)
        except ValueError:
            pass
        raise ZohoBooksApiError(
            status_code=response.status_code,
            code=code,
            message=message,
            body=response.text[:500],
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        accept: str | None = None,
        require_org: bool = True,
    ) -> httpx.Response:
        token = await self._get_access_token()
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        if accept:
            headers["Accept"] = accept
        query = {**(params or {})}
        if require_org:
            query.update(self._org_params())
        url = f"{self.settings.zoho_books_api_url.rstrip('/')}/{path.lstrip('/')}"

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.request(method, url, headers=headers, params=query, json=json)
            if response.status_code == 401:
                token = await self._get_access_token(force_refresh=True)
                headers["Authorization"] = f"Zoho-oauthtoken {token}"
                response = await client.request(method, url, headers=headers, params=query, json=json)
            self._raise_for_zoho_response(response)
            return response

    async def list_organizations(self) -> list[dict[str, Any]]:
        """GET /organizations — used to pick ZOHO_ORGANIZATION_ID."""
        response = await self._request("GET", "/organizations", require_org=False)
        orgs = response.json().get("organizations") or []
        return [
            {
                "organization_id": str(o.get("organization_id") or ""),
                "name": o.get("name"),
                "currency_code": o.get("currency_code"),
                "is_default_org": o.get("is_default_org"),
            }
            for o in orgs
            if isinstance(o, dict)
        ]

    async def test_connection(self) -> dict[str, Any]:
        missing = []
        for key, attr in (
            ("ZOHO_CLIENT_ID", "zoho_client_id"),
            ("ZOHO_CLIENT_SECRET", "zoho_client_secret"),
            ("ZOHO_REFRESH_TOKEN", "zoho_refresh_token"),
            ("ZOHO_ORGANIZATION_ID", "zoho_organization_id"),
        ):
            if not getattr(self.settings, attr, None):
                missing.append(key)
        if missing:
            return {
                "ok": False,
                "mode": "live_incomplete",
                "missing": missing,
                "message": "Set the missing Zoho env vars on Railway, then re-check /api/dev/zoho/status",
            }

        orgs = await self.list_organizations()
        org_id = self.settings.zoho_organization_id
        matched = next((o for o in orgs if o.get("organization_id") == org_id), None)
        # Also verify invoices endpoint is reachable for this org
        await self._request("GET", "/invoices", params={"per_page": 1, "page": 1})
        return {
            "ok": True,
            "mode": "live",
            "organization_id": org_id,
            "organization_name": (matched or {}).get("name"),
            "organization_matched": matched is not None,
            "organizations": orgs,
            "api_url": self.settings.zoho_books_api_url,
            "accounts_url": self.settings.zoho_accounts_url,
            "message": "Zoho Books connection OK — invoice create path is ready",
        }

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
        payload: dict[str, Any] = {
            "contact_name": name,
            "contact_type": "customer",
        }
        if customer_email:
            payload["email"] = customer_email

        try:
            response = await self._request("POST", "/contacts", json=payload)
        except ZohoBooksApiError as exc:
            # 3062 = contact_name already exists — reuse that customer instead of failing invoice.
            if str(exc.code) != "3062" and "already exists" not in (exc.message or "").lower():
                raise
            existing = await self._request(
                "GET",
                "/contacts",
                params={"contact_name": name},
            )
            contacts = existing.json().get("contacts") or []
            if not contacts:
                # Fallback: unique display name so invoice creation can continue.
                unique_name = f"{name} ({email_key})" if email_key else f"{name} ({uuid.uuid4().hex[:6]})"
                payload["contact_name"] = unique_name
                response = await self._request("POST", "/contacts", json=payload)
                contact = response.json().get("contact") or {}
                contact_id = str(contact["contact_id"])
                if email_key:
                    self._customer_ids[email_key] = contact_id
                logger.info(
                    "Zoho contact created with unique name id=%s name=%s email=%s",
                    contact_id,
                    unique_name,
                    email_key or "-",
                )
                return contact_id
            contact_id = str(contacts[0]["contact_id"])
            if email_key:
                self._customer_ids[email_key] = contact_id
            logger.info(
                "Zoho contact reused after name conflict id=%s name=%s email=%s",
                contact_id,
                name,
                email_key or "-",
            )
            return contact_id

        contact = response.json().get("contact") or {}
        contact_id = str(contact["contact_id"])
        if email_key:
            self._customer_ids[email_key] = contact_id
        logger.info("Zoho contact created id=%s email=%s", contact_id, email_key or "-")
        return contact_id

    def _line_items(self, *, total_amount: Decimal, currency: str) -> list[dict]:
        item: dict[str, Any] = {
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
        payment_mode: str = "others",
    ) -> None:
        if amount <= 0:
            return
        payload = {
            "customer_id": customer_id,
            "payment_mode": payment_mode,
            "amount": float(amount),
            "date": date.today().isoformat(),
            "reference_number": transaction_id[:50],
            "invoices": [{"invoice_id": invoice_id, "amount_applied": float(amount)}],
        }
        await self._request("POST", "/customerpayments", json=payload)
        logger.info(
            "Zoho customer payment recorded | invoice=%s amount=%s mode=%s",
            invoice_id,
            amount,
            payment_mode,
        )

    async def _mark_invoice_sent(self, invoice_id: str) -> None:
        try:
            await self._request("POST", f"/invoices/{invoice_id}/status/sent")
            logger.info("Zoho invoice %s marked as sent", invoice_id)
        except Exception:
            logger.exception("Failed to mark Zoho invoice %s as sent", invoice_id)

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

    @staticmethod
    def _payment_mode_for_transaction(transaction_id: str) -> str:
        # Cash Desk transactions use cash-* ids; Zoho accepts "cash" / "others" / …
        if transaction_id.lower().startswith("cash"):
            return "cash"
        return "others"

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
            "date": date.today().isoformat(),
            "line_items": self._line_items(total_amount=total_amount, currency=currency),
            "reference_number": f"WF-{workflow_id}-{transaction_id}"[:50],
            "notes": f"Learners Point finance workflow {workflow_id}",
        }
        logger.info(
            "Zoho create invoice | workflow_id=%s customer_id=%s total=%s paid=%s %s",
            workflow_id,
            customer_id,
            total_amount,
            amount_paid,
            currency,
        )
        response = await self._request("POST", "/invoices", json=payload)
        invoice = response.json().get("invoice") or {}
        invoice_id = str(invoice["invoice_id"])
        invoice_number = str(invoice.get("invoice_number") or invoice_id)

        await self._mark_invoice_sent(invoice_id)
        await self._record_payment(
            customer_id=customer_id,
            invoice_id=invoice_id,
            amount=amount_paid,
            transaction_id=transaction_id,
            payment_mode=self._payment_mode_for_transaction(transaction_id),
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
            payment_mode=self._payment_mode_for_transaction(transaction_id),
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
