"""Paymob integration — real stub and mock implementation."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.base import PaymentWebhookData, PaymobSession

logger = logging.getLogger(__name__)


class MockPaymobClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def create_payment_session(
        self,
        *,
        amount: Decimal,
        currency: str,
        merchant_reference: str,
        customer_email: str | None,
        customer_name: str | None,
    ) -> PaymobSession:
        session_id = uuid.uuid4().hex[:16]
        checkout_url = f"https://mock.paymob/checkout/{session_id}"
        logger.info(
            "[MockPaymob] Created session %s for %s %s (ref=%s)",
            session_id,
            currency,
            amount,
            merchant_reference,
        )
        return PaymobSession(session_id=session_id, checkout_url=checkout_url, order_id=f"ORD-{session_id}")

    def verify_webhook(self, payload: dict[str, Any], signature: str | None) -> bool:
        if self.settings.use_mock_integrations:
            return True
        if not self.settings.paymob_hmac_secret:
            return True
        if not signature:
            return False
        calculated = self._calculate_hmac(payload)
        return hmac.compare_digest(calculated, signature)

    def parse_successful_payment(self, payload: dict[str, Any]) -> PaymentWebhookData | None:
        obj = payload.get("obj") or payload
        success = obj.get("success")
        if success is False or str(success).lower() == "false":
            return None

        transaction_id = str(
            obj.get("id") or obj.get("transaction_id") or payload.get("transaction_id") or uuid.uuid4().hex
        )
        amount_cents = obj.get("amount_cents") or payload.get("amount_cents") or 0
        amount = Decimal(str(amount_cents)) / Decimal("100") if amount_cents else Decimal(str(payload.get("amount", 0)))
        currency = str(obj.get("currency") or payload.get("currency") or self.settings.default_currency)
        merchant_reference = str(
            obj.get("merchant_order_id")
            or obj.get("order", {}).get("merchant_order_id")
            or payload.get("merchant_reference")
            or ""
        )
        if not merchant_reference:
            return None

        return PaymentWebhookData(
            transaction_id=transaction_id,
            amount=amount,
            currency=currency,
            merchant_reference=merchant_reference,
            order_id=str(obj.get("order", {}).get("id") or payload.get("order_id") or ""),
            raw_payload=json.dumps(payload),
        )

    def _calculate_hmac(self, payload: dict[str, Any]) -> str:
        obj = payload.get("obj") or payload
        concatenated = "".join(str(obj.get(k, "")) for k in sorted(obj.keys()))
        return hmac.new(
            self.settings.paymob_hmac_secret.encode(),
            concatenated.encode(),
            hashlib.sha512,
        ).hexdigest()


class RealPaymobClient(MockPaymobClient):
    """Real Paymob client — extends mock parsing, adds API calls when configured."""

    async def create_payment_session(
        self,
        *,
        amount: Decimal,
        currency: str,
        merchant_reference: str,
        customer_email: str | None,
        customer_name: str | None,
    ) -> PaymobSession:
        if not self.settings.paymob_api_key or self.settings.use_mock_integrations:
            return await super().create_payment_session(
                amount=amount,
                currency=currency,
                merchant_reference=merchant_reference,
                customer_email=customer_email,
                customer_name=customer_name,
            )

        amount_cents = int(amount * 100)
        async with httpx.AsyncClient(timeout=30.0) as client:
            auth_resp = await client.post(
                "https://accept.paymob.com/api/auth/tokens",
                json={"api_key": self.settings.paymob_api_key},
            )
            auth_resp.raise_for_status()
            token = auth_resp.json()["token"]

            intention_resp = await client.post(
                "https://accept.paymob.com/v1/intention/",
                headers={"Authorization": f"Token {token}"},
                json={
                    "amount": amount_cents,
                    "currency": currency,
                    "payment_methods": [self.settings.paymob_integration_id],
                    "special_reference": merchant_reference,
                    "billing_data": {
                        "email": customer_email or "customer@example.com",
                        "first_name": (customer_name or "Customer").split()[0],
                        "last_name": " ".join((customer_name or "Customer").split()[1:]) or "User",
                        "phone_number": "+971500000000",
                        "country": "AE",
                    },
                },
            )
            intention_resp.raise_for_status()
            data = intention_resp.json()

        client_secret = data.get("client_secret", "")
        checkout_url = f"{self.settings.paymob_checkout_base_url}?publicKey={self.settings.paymob_public_key}&clientSecret={client_secret}"
        return PaymobSession(
            session_id=str(data.get("id", "")),
            checkout_url=checkout_url,
            order_id=str(data.get("order_id", "")) if data.get("order_id") else None,
        )
