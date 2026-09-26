"""Tabby direct checkout API (UAE api.tabby.ai)."""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.base import PaymentWebhookData, TabbyCheckoutSession

logger = logging.getLogger(__name__)


def _amount_str(amount: Decimal) -> str:
    return f"{Decimal(amount).quantize(Decimal('0.01'))}"


def _split_name(customer_name: str | None) -> tuple[str, str]:
    name = (customer_name or "Customer").strip() or "Customer"
    parts = name.split()
    first = parts[0]
    last = " ".join(parts[1:]) or "Customer"
    return first, last


def _normalize_phone(phone: str | None) -> str:
    raw = (phone or "").strip().replace(" ", "")
    if not raw:
        return "+971500000001"
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("+"):
        return raw
    if raw.startswith("971"):
        return f"+{raw}"
    if raw.startswith("0"):
        return f"+971{raw[1:]}"
    return f"+971{raw}"


class MockTabbyClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def create_checkout_session(
        self,
        *,
        amount: Decimal,
        currency: str,
        merchant_reference: str,
        customer_email: str | None,
        customer_name: str | None,
        customer_phone: str | None = None,
        item_title: str = "Course payment",
    ) -> TabbyCheckoutSession:
        payment_id = f"tabby_{uuid.uuid4().hex[:16]}"
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        frontend = (
            self.settings.payment_frontend_base_url or self.settings.public_base_url
        ).rstrip("/")
        checkout_url = (
            f"{frontend}/payment/thank-you"
            f"?provider=tabby&status=success&payment_id={payment_id}"
            f"&merchant_order_id={merchant_reference}"
        )
        logger.info(
            "[MockTabby] Created checkout %s for %s %s (ref=%s)",
            payment_id,
            currency,
            amount,
            merchant_reference,
        )
        return TabbyCheckoutSession(
            payment_id=payment_id,
            checkout_url=checkout_url,
            status="created",
            session_id=session_id,
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return {
            "id": payment_id,
            "status": "AUTHORIZED",
            "amount": "0.00",
            "currency": "AED",
            "order": {"reference_id": ""},
            "captures": [],
        }

    async def capture_payment(
        self,
        payment_id: str,
        *,
        amount: Decimal,
        reference_id: str,
    ) -> dict[str, Any]:
        logger.info(
            "[MockTabby] Captured %s amount=%s ref=%s",
            payment_id,
            amount,
            reference_id,
        )
        return {
            "id": payment_id,
            "status": "CLOSED",
            "amount": _amount_str(amount),
            "captures": [
                {
                    "id": f"cap_{uuid.uuid4().hex[:8]}",
                    "amount": _amount_str(amount),
                    "reference_id": reference_id,
                }
            ],
        }

    def verify_webhook_auth(self, header_value: str | None) -> bool:
        expected = (self.settings.tabby_webhook_auth_value or "").strip()
        if self.settings.use_mock_integrations and not expected:
            return True
        if not expected:
            logger.error("TABBY_WEBHOOK_AUTH_VALUE is not configured")
            return False
        return (header_value or "").strip() == expected

    def parse_webhook_payload(self, payload: dict[str, Any]) -> PaymentWebhookData | None:
        if not isinstance(payload, dict):
            return None
        payment_id = str(payload.get("id") or "").strip()
        if not payment_id:
            return None
        order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
        merchant_reference = str(order.get("reference_id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        amount_raw = payload.get("amount") or "0"
        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
        except Exception:
            amount = Decimal("0.00")
        currency = str(payload.get("currency") or "AED").upper()
        success = status in ("authorized", "closed")
        amount_cents = int(amount * 100)
        return PaymentWebhookData(
            transaction_id=payment_id,
            amount=amount,
            currency=currency,
            merchant_reference=merchant_reference,
            order_id=payment_id,
            raw_payload=json.dumps(payload, default=str),
            amount_cents=amount_cents,
            success=success,
            source_type="tabby",
            source_sub_type=status,
        )


class RealTabbyClient(MockTabbyClient):
    """Real Tabby client — POST /api/v2/checkout, payments, captures."""

    def _auth_headers(self, *, include_merchant_code: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.tabby_secret_key}",
            "Content-Type": "application/json",
        }
        if include_merchant_code and self.settings.tabby_merchant_code:
            headers["X-Merchant-Code"] = self.settings.tabby_merchant_code
        return headers

    def _base(self) -> str:
        return (self.settings.tabby_base_url or "https://api.tabby.ai").rstrip("/")

    async def create_checkout_session(
        self,
        *,
        amount: Decimal,
        currency: str,
        merchant_reference: str,
        customer_email: str | None,
        customer_name: str | None,
        customer_phone: str | None = None,
        item_title: str = "Course payment",
    ) -> TabbyCheckoutSession:
        if not self.settings.tabby_secret_key or self.settings.use_mock_integrations:
            return await super().create_checkout_session(
                amount=amount,
                currency=currency,
                merchant_reference=merchant_reference,
                customer_email=customer_email,
                customer_name=customer_name,
                customer_phone=customer_phone,
                item_title=item_title,
            )
        if not (self.settings.tabby_merchant_code or "").strip():
            raise ValueError(
                "Tabby checkout failed: TABBY_MERCHANT_CODE is not configured."
            )

        first, last = _split_name(customer_name)
        email = (customer_email or "").strip()
        if not email or "@" not in email:
            raise ValueError(
                "Tabby checkout failed: a valid customer email is required."
            )
        frontend = (
            self.settings.payment_frontend_base_url or self.settings.public_base_url
        ).rstrip("/")
        amount_s = _amount_str(amount)
        payload = {
            "payment": {
                "amount": amount_s,
                "currency": (currency or "AED").upper(),
                "buyer": {
                    "name": f"{first} {last}".strip(),
                    "email": email,
                    "phone": _normalize_phone(customer_phone),
                },
                "shipping_address": {
                    "city": "Dubai",
                    "address": "Learners Point",
                    "zip": "00000",
                },
                "order": {
                    "reference_id": merchant_reference,
                    "items": [
                        {
                            "title": (item_title or "Course payment")[:255],
                            "quantity": 1,
                            "unit_price": amount_s,
                            "category": "Education",
                        }
                    ],
                },
                "buyer_history": {
                    "registered_since": "2024-01-01T00:00:00Z",
                    "loyalty_level": 0,
                },
                "order_history": [],
            },
            "lang": "en",
            "merchant_code": self.settings.tabby_merchant_code,
            "merchant_urls": {
                "success": (
                    f"{frontend}/payment/thank-you"
                    f"?provider=tabby&status=success"
                    f"&merchant_order_id={merchant_reference}"
                ),
                "cancel": (
                    f"{frontend}/payment/thank-you"
                    f"?provider=tabby&status=cancel"
                    f"&merchant_order_id={merchant_reference}"
                ),
                "failure": (
                    f"{frontend}/payment/thank-you"
                    f"?provider=tabby&status=failure"
                    f"&merchant_order_id={merchant_reference}"
                ),
            },
        }

        url = f"{self._base()}/api/v2/checkout"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, headers=self._auth_headers(), json=payload
            )

        if response.status_code >= 400:
            body = response.text[:800]
            logger.error(
                "Tabby checkout failed status=%s body=%s",
                response.status_code,
                body,
            )
            raise ValueError(
                f"Tabby checkout failed ({response.status_code}): {body}"
            )

        data = response.json()
        status = str(data.get("status") or "").strip().lower()
        payment = data.get("payment") if isinstance(data.get("payment"), dict) else {}
        payment_id = str(payment.get("id") or "").strip()
        session_id = str(data.get("id") or "").strip() or None

        if status == "rejected" or not payment_id:
            rejection = data.get("configuration") or data.get("rejection_reason") or data
            raise ValueError(
                "Tabby rejected this checkout (customer not eligible or missing "
                f"details). Response: {json.dumps(rejection, default=str)[:500]}"
            )

        products = (
            (data.get("configuration") or {}).get("available_products")
            if isinstance(data.get("configuration"), dict)
            else {}
        )
        installments = (
            products.get("installments") if isinstance(products, dict) else None
        ) or []
        web_url = None
        if isinstance(installments, list) and installments:
            first_product = installments[0] if isinstance(installments[0], dict) else {}
            web_url = first_product.get("web_url")

        if not web_url:
            raise ValueError(
                "Tabby checkout created but no installments web_url was returned "
                "(customer may not be eligible)."
            )

        logger.info(
            "Tabby checkout created payment_id=%s ref=%s status=%s",
            payment_id,
            merchant_reference,
            status,
        )
        return TabbyCheckoutSession(
            payment_id=payment_id,
            checkout_url=str(web_url),
            status=status or "created",
            session_id=session_id,
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        if not self.settings.tabby_secret_key or self.settings.use_mock_integrations:
            return await super().get_payment(payment_id)
        url = f"{self._base()}/api/v2/payments/{payment_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self._auth_headers())
        if response.status_code >= 400:
            raise ValueError(
                f"Tabby get payment failed ({response.status_code}): {response.text[:500]}"
            )
        return response.json()

    async def capture_payment(
        self,
        payment_id: str,
        *,
        amount: Decimal,
        reference_id: str,
    ) -> dict[str, Any]:
        if not self.settings.tabby_secret_key or self.settings.use_mock_integrations:
            return await super().capture_payment(
                payment_id, amount=amount, reference_id=reference_id
            )
        url = f"{self._base()}/api/v2/payments/{payment_id}/captures"
        body = {
            "amount": _amount_str(amount),
            "reference_id": reference_id,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, headers=self._auth_headers(), json=body
            )
        if response.status_code >= 400:
            # Idempotent retry: already closed is OK
            text = response.text[:800]
            if response.status_code == 400 and (
                "closed" in text.lower() or "already" in text.lower()
            ):
                logger.info(
                    "Tabby capture already closed payment_id=%s: %s",
                    payment_id,
                    text,
                )
                return await self.get_payment(payment_id)
            raise ValueError(
                f"Tabby capture failed ({response.status_code}): {text}"
            )
        return response.json()
