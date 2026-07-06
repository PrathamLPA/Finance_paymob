"""Paymob integration — aligned with developers.paymob.com webhook spec."""

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

# HMAC field order per Paymob transaction callback documentation
HMAC_FIELD_ORDER = [
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order_id",
    "owner",
    "pending",
    "source_data_pan",
    "source_data_sub_type",
    "source_data_type",
    "success",
]


def _bool_str(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value) if value is not None else ""


def build_transaction_hmac_concat(obj: dict[str, Any]) -> str:
    order = obj.get("order") or {}
    source = obj.get("source_data") or {}
    values = [
        obj.get("amount_cents", ""),
        obj.get("created_at", ""),
        obj.get("currency", ""),
        _bool_str(obj.get("error_occured", False)),
        _bool_str(obj.get("has_parent_transaction", False)),
        obj.get("id", ""),
        obj.get("integration_id", ""),
        _bool_str(obj.get("is_3d_secure", False)),
        _bool_str(obj.get("is_auth", False)),
        _bool_str(obj.get("is_capture", False)),
        _bool_str(obj.get("is_refunded", False)),
        _bool_str(obj.get("is_standalone_payment", True)),
        _bool_str(obj.get("is_voided", False)),
        order.get("id", "") if isinstance(order, dict) else "",
        obj.get("owner", ""),
        _bool_str(obj.get("pending", False)),
        source.get("pan", "") if isinstance(source, dict) else "",
        source.get("sub_type", "") if isinstance(source, dict) else "",
        source.get("type", "") if isinstance(source, dict) else "",
        _bool_str(obj.get("success", False)),
    ]
    return "".join(str(v) for v in values)


def build_mock_paymob_payload(
    *,
    transaction_id: int,
    amount_cents: int,
    currency: str,
    merchant_order_id: str,
    order_id: int,
    integration_id: int = 123456,
    email: str = "customer@example.com",
) -> dict[str, Any]:
    """Build a realistic Paymob webhook payload for mock/dev use."""
    return {
        "type": "TRANSACTION",
        "obj": {
            "id": transaction_id,
            "pending": False,
            "amount_cents": amount_cents,
            "success": True,
            "is_auth": False,
            "is_capture": False,
            "is_standalone_payment": True,
            "is_voided": False,
            "is_refunded": False,
            "is_3d_secure": True,
            "integration_id": integration_id,
            "has_parent_transaction": False,
            "owner": 1,
            "error_occured": False,
            "created_at": "2026-07-06T10:30:00.000000",
            "currency": currency,
            "source_data": {
                "pan": "2346",
                "type": "card",
                "sub_type": "MasterCard",
                "tenure": None,
            },
            "api_source": "IFRAME",
            "terminal_id": None,
            "is_void": False,
            "is_refund": False,
            "data": {},
            "is_hidden": False,
            "payment_key_claims": {"email": email},
            "error_occured": False,
            "is_live": False,
            "other_endpoint_reference": None,
            "refunded_amount_cents": 0,
            "source_id": -1,
            "is_captured": False,
            "captured_amount": 0,
            "merchant_staff_tag": None,
            "paymob_date": None,
            "value": None,
            "currency_symbol": currency,
            "order": {
                "id": order_id,
                "created_at": "2026-07-06T10:29:00.000000",
                "delivery_needed": False,
                "merchant": {"id": 1, "created_at": "2020-01-01", "phones": [], "company_emails": [], "company_name": "Finance", "state": "", "country": "AE", "city": "Dubai", "postal_code": "", "street": ""},
                "collector": None,
                "amount_cents": amount_cents,
                "shipping_data": None,
                "currency": currency,
                "is_payment_locked": False,
                "merchant_order_id": merchant_order_id,
                "wallet_notification": None,
                "paid_amount_cents": amount_cents,
                "items": [],
            },
        },
    }


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
        checkout_url = (
            f"{self.settings.paymob_checkout_base_url.rstrip('/')}"
            f"?publicKey=mock_public_key&clientSecret=mock_{session_id}"
        )
        logger.info(
            "[MockPaymob] Created intention %s for %s %s (ref=%s)",
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
        obj = payload.get("obj") or payload
        calculated = hmac.new(
            self.settings.paymob_hmac_secret.encode(),
            build_transaction_hmac_concat(obj).encode(),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(calculated, signature)

    def parse_successful_payment(self, payload: dict[str, Any]) -> PaymentWebhookData | None:
        obj = payload.get("obj") or payload
        success = obj.get("success")
        if success is False or str(success).lower() == "false":
            return None

        order = obj.get("order") or {}
        source = obj.get("source_data") or {}
        amount_cents = int(obj.get("amount_cents") or 0)
        amount = Decimal(amount_cents) / Decimal("100") if amount_cents else Decimal("0")

        merchant_reference = str(
            order.get("merchant_order_id")
            or obj.get("merchant_order_id")
            or payload.get("merchant_reference")
            or ""
        )
        if not merchant_reference:
            return None

        transaction_id = str(obj.get("id") or payload.get("transaction_id") or uuid.uuid4().hex)

        return PaymentWebhookData(
            transaction_id=transaction_id,
            amount=amount,
            currency=str(obj.get("currency") or payload.get("currency") or self.settings.default_currency),
            merchant_reference=merchant_reference,
            order_id=str(order.get("id") or payload.get("order_id") or ""),
            raw_payload=json.dumps(payload),
            amount_cents=amount_cents,
            paymob_created_at=str(obj.get("created_at") or ""),
            error_occured=bool(obj.get("error_occured", False)),
            has_parent_transaction=bool(obj.get("has_parent_transaction", False)),
            paymob_integration_id=int(obj["integration_id"]) if obj.get("integration_id") is not None else None,
            is_3d_secure=bool(obj.get("is_3d_secure", False)),
            is_auth=bool(obj.get("is_auth", False)),
            is_capture=bool(obj.get("is_capture", False)),
            is_refunded=bool(obj.get("is_refunded", False)),
            is_standalone_payment=bool(obj.get("is_standalone_payment", True)),
            is_voided=bool(obj.get("is_voided", False)),
            paymob_order_id=str(order.get("id") or ""),
            owner=int(obj["owner"]) if obj.get("owner") is not None else None,
            pending=bool(obj.get("pending", False)),
            source_pan=str(source.get("pan") or "") or None,
            source_sub_type=str(source.get("sub_type") or "") or None,
            source_type=str(source.get("type") or "") or None,
            success=True,
        )


class RealPaymobClient(MockPaymobClient):
    """Real Paymob client using Intention API (developers.paymob.com)."""

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
        name = customer_name or "Customer"
        first_name = name.split()[0]
        last_name = " ".join(name.split()[1:]) or "User"

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
                        "first_name": first_name,
                        "last_name": last_name,
                        "phone_number": "+971500000000",
                        "country": "AE",
                    },
                },
            )
            intention_resp.raise_for_status()
            data = intention_resp.json()

        client_secret = data.get("client_secret", "")
        checkout_url = (
            f"{self.settings.paymob_checkout_base_url.rstrip('/')}"
            f"?publicKey={self.settings.paymob_public_key}&clientSecret={client_secret}"
        )
        return PaymobSession(
            session_id=str(data.get("id", "")),
            checkout_url=checkout_url,
            order_id=str(data.get("order_id", "")) if data.get("order_id") else None,
        )
