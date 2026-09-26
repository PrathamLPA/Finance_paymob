"""Tamara direct checkout API (UAE api-sandbox.tamara.co / api.tamara.co)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import jwt

from app.config import Settings, get_settings
from app.integrations.base import PaymentWebhookData, TamaraCheckoutSession

logger = logging.getLogger(__name__)


def _money(amount: Decimal, currency: str) -> dict[str, Any]:
    return {
        "amount": float(Decimal(amount).quantize(Decimal("0.01"))),
        "currency": (currency or "AED").upper(),
    }


def _split_name(customer_name: str | None) -> tuple[str, str]:
    name = (customer_name or "Customer").strip() or "Customer"
    parts = name.split()
    first = parts[0]
    last = " ".join(parts[1:]) or "Customer"
    return first, last


def _normalize_phone(phone: str | None) -> str:
    """Tamara UAE phones are often without +; keep digits (971…)."""
    raw = (phone or "").strip().replace(" ", "").replace("-", "")
    if not raw:
        return "971500000001"
    if raw.startswith("00"):
        raw = raw[2:]
    if raw.startswith("+"):
        raw = raw[1:]
    if raw.startswith("0") and not raw.startswith("971"):
        raw = f"971{raw[1:]}"
    if not raw.startswith("971"):
        raw = f"971{raw}"
    return raw


class MockTamaraClient:
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
    ) -> TamaraCheckoutSession:
        order_id = str(uuid.uuid4())
        checkout_id = str(uuid.uuid4())
        frontend = (
            self.settings.payment_frontend_base_url or self.settings.public_base_url
        ).rstrip("/")
        checkout_url = (
            f"{frontend}/payment/thank-you"
            f"?provider=tamara&status=success&order_id={order_id}"
            f"&merchant_order_id={merchant_reference}"
        )
        logger.info(
            "[MockTamara] Created checkout %s for %s %s (ref=%s)",
            order_id,
            currency,
            amount,
            merchant_reference,
        )
        return TamaraCheckoutSession(
            order_id=order_id,
            checkout_url=checkout_url,
            status="new",
            checkout_id=checkout_id,
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "status": "approved",
            "total_amount": {"amount": 0, "currency": "AED"},
        }

    async def authorise_order(self, order_id: str) -> dict[str, Any]:
        logger.info("[MockTamara] Authorised %s", order_id)
        return {
            "order_id": order_id,
            "status": "authorised",
            "auto_captured": False,
        }

    async def capture_order(
        self,
        order_id: str,
        *,
        amount: Decimal,
        currency: str,
        item_title: str = "Course payment",
    ) -> dict[str, Any]:
        logger.info("[MockTamara] Captured %s amount=%s", order_id, amount)
        return {
            "order_id": order_id,
            "status": "fully_captured",
            "capture_id": str(uuid.uuid4()),
            "captured_amount": _money(amount, currency),
        }

    def verify_webhook_token(self, token: str | None) -> bool:
        expected = (self.settings.tamara_notification_token or "").strip()
        if self.settings.use_mock_integrations and not expected:
            return True
        if not expected or not token:
            return False
        # Accept raw token match (some setups) or JWT signed with notification token.
        if token.strip() == expected:
            return True
        try:
            jwt.decode(
                token,
                expected,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            return True
        except Exception:
            logger.warning("Tamara webhook JWT verification failed")
            return False

    def parse_webhook_payload(self, payload: dict[str, Any]) -> PaymentWebhookData | None:
        if not isinstance(payload, dict):
            return None
        order_id = str(payload.get("order_id") or "").strip()
        if not order_id:
            return None
        merchant_reference = str(payload.get("order_reference_id") or "").strip()
        event = str(payload.get("event_type") or "").strip().lower()
        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        amount = Decimal("0.00")
        currency = "AED"
        captured = data_obj.get("captured_amount") if isinstance(data_obj, dict) else None
        if isinstance(captured, dict):
            try:
                amount = Decimal(str(captured.get("amount") or "0")).quantize(
                    Decimal("0.01")
                )
            except Exception:
                amount = Decimal("0.00")
            currency = str(captured.get("currency") or currency).upper()

        success_events = {
            "order_approved",
            "order_authorised",
            "order_authorized",
            "order_captured",
            "order_fully_captured",
        }
        failure_events = {
            "order_declined",
            "order_canceled",
            "order_cancelled",
            "order_expired",
        }
        success = event in success_events
        if event in failure_events:
            success = False
        return PaymentWebhookData(
            transaction_id=order_id,
            amount=amount,
            currency=currency,
            merchant_reference=merchant_reference,
            order_id=order_id,
            raw_payload=json.dumps(payload, default=str),
            amount_cents=int(amount * 100) if amount else None,
            success=success,
            source_type="tamara",
            source_sub_type=event,
        )


class RealTamaraClient(MockTamaraClient):
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.tamara_api_token}",
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return (self.settings.tamara_base_url or "https://api.tamara.co").rstrip("/")

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
    ) -> TamaraCheckoutSession:
        if not self.settings.tamara_api_token or self.settings.use_mock_integrations:
            return await super().create_checkout_session(
                amount=amount,
                currency=currency,
                merchant_reference=merchant_reference,
                customer_email=customer_email,
                customer_name=customer_name,
                customer_phone=customer_phone,
                item_title=item_title,
            )

        first, last = _split_name(customer_name)
        email = (customer_email or "").strip()
        if not email or "@" not in email:
            raise ValueError(
                "Tamara checkout failed: a valid customer email is required."
            )
        phone = _normalize_phone(customer_phone)
        cur = (currency or "AED").upper()
        amt = Decimal(amount).quantize(Decimal("0.01"))
        frontend = (
            self.settings.payment_frontend_base_url or self.settings.public_base_url
        ).rstrip("/")
        public = (self.settings.public_base_url or frontend).rstrip("/")
        country = (self.settings.tamara_country_code or "AE").upper()
        payment_type = (
            self.settings.tamara_payment_type or "PAY_BY_INSTALMENTS"
        ).upper()
        instalments = int(self.settings.tamara_instalments or 3)
        title = (item_title or "Course payment")[:255]

        payload: dict[str, Any] = {
            "order_reference_id": merchant_reference,
            "order_number": merchant_reference,
            "total_amount": _money(amt, cur),
            "description": title,
            "country_code": country,
            "payment_type": payment_type,
            "locale": "en_US",
            "items": [
                {
                    "reference_id": merchant_reference,
                    "type": "Digital",
                    "name": title,
                    "sku": merchant_reference[:128],
                    "quantity": 1,
                    "unit_price": _money(amt, cur),
                    "total_amount": _money(amt, cur),
                    "tax_amount": _money(Decimal("0.00"), cur),
                    "discount_amount": _money(Decimal("0.00"), cur),
                }
            ],
            "consumer": {
                "first_name": first,
                "last_name": last,
                "email": email,
                "phone_number": phone,
            },
            "shipping_address": {
                "first_name": first,
                "last_name": last,
                "line1": "Learners Point",
                "city": "Dubai",
                "region": "Dubai",
                "postal_code": "00000",
                "country_code": country,
                "phone_number": phone,
            },
            "tax_amount": _money(Decimal("0.00"), cur),
            "shipping_amount": _money(Decimal("0.00"), cur),
            "merchant_url": {
                "success": (
                    f"{frontend}/payment/thank-you"
                    f"?provider=tamara&status=success"
                    f"&merchant_order_id={merchant_reference}"
                ),
                "failure": (
                    f"{frontend}/payment/thank-you"
                    f"?provider=tamara&status=failure"
                    f"&merchant_order_id={merchant_reference}"
                ),
                "cancel": (
                    f"{frontend}/payment/thank-you"
                    f"?provider=tamara&status=cancel"
                    f"&merchant_order_id={merchant_reference}"
                ),
                "notification": f"{public}/webhooks/tamara",
            },
            # OpenAPI marks instalments as required on /checkout.
            "instalments": instalments if payment_type == "PAY_BY_INSTALMENTS" else 1,
        }

        url = f"{self._base()}/checkout"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, headers=self._auth_headers(), json=payload
            )

        if response.status_code >= 400:
            body = response.text[:800]
            logger.error(
                "Tamara checkout failed status=%s body=%s",
                response.status_code,
                body,
            )
            raise ValueError(
                f"Tamara checkout failed ({response.status_code}): {body}"
            )

        data = response.json()
        order_id = str(data.get("order_id") or "").strip()
        checkout_url = str(data.get("checkout_url") or "").strip()
        status = str(data.get("status") or "").strip()
        checkout_id = str(data.get("checkout_id") or "").strip() or None
        if not order_id or not checkout_url:
            raise ValueError(
                "Tamara checkout response missing order_id or checkout_url: "
                f"{json.dumps(data, default=str)[:500]}"
            )
        logger.info(
            "Tamara checkout created order_id=%s ref=%s status=%s",
            order_id,
            merchant_reference,
            status,
        )
        return TamaraCheckoutSession(
            order_id=order_id,
            checkout_url=checkout_url,
            status=status or "new",
            checkout_id=checkout_id,
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        if not self.settings.tamara_api_token or self.settings.use_mock_integrations:
            return await super().get_order(order_id)
        url = f"{self._base()}/orders/{order_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self._auth_headers())
        if response.status_code >= 400:
            raise ValueError(
                f"Tamara get order failed ({response.status_code}): {response.text[:500]}"
            )
        return response.json()

    async def authorise_order(self, order_id: str) -> dict[str, Any]:
        if not self.settings.tamara_api_token or self.settings.use_mock_integrations:
            return await super().authorise_order(order_id)
        url = f"{self._base()}/orders/{order_id}/authorise"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=self._auth_headers())
        if response.status_code >= 400:
            text = response.text[:800]
            # Already authorised / captured is OK for idempotency
            if response.status_code in (400, 409) and any(
                w in text.lower()
                for w in ("authoris", "authoriz", "captured", "already")
            ):
                logger.info(
                    "Tamara authorise already done order_id=%s: %s", order_id, text
                )
                return await self.get_order(order_id)
            raise ValueError(
                f"Tamara authorise failed ({response.status_code}): {text}"
            )
        return response.json()

    async def capture_order(
        self,
        order_id: str,
        *,
        amount: Decimal,
        currency: str,
        item_title: str = "Course payment",
    ) -> dict[str, Any]:
        if not self.settings.tamara_api_token or self.settings.use_mock_integrations:
            return await super().capture_order(
                order_id,
                amount=amount,
                currency=currency,
                item_title=item_title,
            )
        cur = (currency or "AED").upper()
        amt = Decimal(amount).quantize(Decimal("0.01"))
        title = (item_title or "Course payment")[:255]
        body = {
            "order_id": order_id,
            "total_amount": _money(amt, cur),
            "shipping_amount": _money(Decimal("0.00"), cur),
            "tax_amount": _money(Decimal("0.00"), cur),
            "discount_amount": _money(Decimal("0.00"), cur),
            "shipping_info": {
                "shipped_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                ),
                "shipping_company": "Digital delivery",
                "tracking_number": order_id[:32],
            },
            "items": [
                {
                    "reference_id": order_id,
                    "type": "Digital",
                    "name": title,
                    "sku": order_id[:128],
                    "quantity": 1,
                    "unit_price": _money(amt, cur),
                    "total_amount": _money(amt, cur),
                    "tax_amount": _money(Decimal("0.00"), cur),
                    "discount_amount": _money(Decimal("0.00"), cur),
                }
            ],
        }
        url = f"{self._base()}/payments/capture"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, headers=self._auth_headers(), json=body
            )
        if response.status_code >= 400:
            text = response.text[:800]
            if response.status_code in (400, 409) and "captur" in text.lower():
                logger.info(
                    "Tamara capture already done order_id=%s: %s", order_id, text
                )
                return await self.get_order(order_id)
            raise ValueError(
                f"Tamara capture failed ({response.status_code}): {text}"
            )
        return response.json()
