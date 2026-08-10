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


def extract_transaction_obj(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle both legacy ({"obj": …}) and UAE Intention ({"transaction": …}) callbacks."""
    for key in ("obj", "transaction"):
        candidate = payload.get(key)
        if isinstance(candidate, dict) and candidate:
            return candidate
    return payload


def extract_order_id(obj: dict[str, Any]) -> Any:
    """Paymob sends order as a nested object, a bare id, or a flat order_id."""
    order = obj.get("order")
    if isinstance(order, dict):
        return order.get("id", "")
    if isinstance(order, (int, str)) and order != "":
        return order
    for key in ("order_id", "order.id"):
        if obj.get(key) is not None:
            return obj[key]
    return ""


def extract_source_field(obj: dict[str, Any], field: str) -> Any:
    """source_data arrives nested, dot-flattened, or underscore-flattened."""
    source = obj.get("source_data")
    if isinstance(source, dict) and field in source:
        return source.get(field, "")
    for key in (f"source_data.{field}", f"source_data_{field}"):
        if obj.get(key) is not None:
            return obj[key]
    return ""


def build_transaction_hmac_concat(obj: dict[str, Any]) -> str:
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
        extract_order_id(obj),
        obj.get("owner", ""),
        _bool_str(obj.get("pending", False)),
        extract_source_field(obj, "pan"),
        extract_source_field(obj, "sub_type"),
        extract_source_field(obj, "type"),
        _bool_str(obj.get("success", False)),
    ]
    return "".join(str(v) for v in values)


def missing_transaction_hmac_fields(obj: dict[str, Any]) -> list[str]:
    """Return absent fields that Paymob includes in its transaction HMAC."""
    direct_fields = (
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
        "owner",
        "pending",
        "success",
    )
    missing = [field for field in direct_fields if obj.get(field) is None]
    if extract_order_id(obj) == "":
        missing.append("order_id")
    for field in ("pan", "sub_type", "type"):
        if extract_source_field(obj, field) == "":
            missing.append(f"source_data_{field}")
    return missing


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
            logger.debug("Paymob HMAC verification bypassed reason=mock_integrations")
            return True
        if not self.settings.paymob_hmac_secret:
            logger.error(
                "Paymob HMAC verification failed reason=secret_not_configured "
                "action=set_PAYMOB_HMAC_SECRET"
            )
            return False
        if not signature:
            logger.warning("Paymob HMAC verification failed reason=signature_missing")
            return False
        obj = extract_transaction_obj(payload)
        concat = build_transaction_hmac_concat(obj)
        received = str(signature).strip().lower()
        calculated = hmac.new(
            self.settings.paymob_hmac_secret.encode(),
            concat.encode(),
            hashlib.sha512,
        ).hexdigest()
        if hmac.compare_digest(calculated, received):
            logger.info(
                "Paymob HMAC verified | txn=%s integration_id=%s",
                obj.get("id") or "-",
                obj.get("integration_id") or "-",
            )
            return True

        missing_fields = missing_transaction_hmac_fields(obj)
        payload_shape = (
            "obj"
            if isinstance(payload.get("obj"), dict)
            else "transaction"
            if isinstance(payload.get("transaction"), dict)
            else "root"
        )
        order_shape = type(obj.get("order")).__name__
        source_shape = type(obj.get("source_data")).__name__
        secret_fingerprint = hashlib.sha256(
            self.settings.paymob_hmac_secret.encode()
        ).hexdigest()[:8]
        likely_cause = (
            "malformed_signature"
            if len(received) != 128
            else "missing_or_differently_named_fields"
            if missing_fields
            else "wrong_hmac_secret_or_value_format"
        )
        logger.warning(
            "Paymob HMAC verification failed | txn=%s reason=mismatch likely=%s "
            "shape=%s order_shape=%s source_shape=%s missing_fields=%s "
            "signature_len=%s calculated=%s… received=%s… "
            "secret_len=%s secret_fingerprint=%s concat_len=%s concat_sha256=%s",
            obj.get("id") or "-",
            likely_cause,
            payload_shape,
            order_shape,
            source_shape,
            missing_fields or "none",
            len(received),
            calculated[:16],
            received[:16],
            len(self.settings.paymob_hmac_secret),
            secret_fingerprint,
            len(concat),
            hashlib.sha256(concat.encode()).hexdigest()[:16],
        )
        logger.debug(
            "Paymob HMAC transaction keys txn=%s keys=%s",
            obj.get("id") or "-",
            sorted(obj.keys()),
        )
        return False

    def parse_successful_payment(self, payload: dict[str, Any]) -> PaymentWebhookData | None:
        obj = extract_transaction_obj(payload)
        success = obj.get("success")
        if success is False or str(success).lower() == "false":
            return None

        order = obj.get("order") or {}
        source = obj.get("source_data") or {}
        amount_cents = int(obj.get("amount_cents") or 0)
        amount = Decimal(amount_cents) / Decimal("100") if amount_cents else Decimal("0")

        intention = payload.get("intention") if isinstance(payload.get("intention"), dict) else {}
        merchant_reference = str(
            order.get("merchant_order_id")
            or obj.get("merchant_order_id")
            or intention.get("special_reference")
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
        if not self.settings.paymob_secret_key or self.settings.use_mock_integrations:
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
        base = self.settings.paymob_base_url.rstrip("/")
        email = customer_email or "customer@example.com"
        na = "NA"

        intention_payload = {
            "amount": amount_cents,
            "currency": currency,
            "payment_methods": [self.settings.paymob_integration_id],
            "special_reference": merchant_reference,
            "items": [
                {
                    "name": "Course payment",
                    "amount": amount_cents,
                    "description": merchant_reference,
                    "quantity": 1,
                }
            ],
            "billing_data": {
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "phone_number": "+971500000000",
                "apartment": na,
                "floor": na,
                "street": na,
                "building": na,
                "shipping_method": na,
                "postal_code": na,
                "city": na,
                "country": "AE",
                "state": na,
            },
            "customer": {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
            },
            "notification_url": f"{self.settings.public_base_url.rstrip('/')}/webhooks/paymob",
            "redirection_url": (
                f"{(self.settings.payment_frontend_base_url or self.settings.public_base_url).rstrip('/')}"
                f"/payment/thank-you"
            ),
        }

        headers = {
            "Authorization": f"Token {self.settings.paymob_secret_key}",
            "Content-Type": "application/json",
            "Expect": "",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            intention_resp = await client.post(
                f"{base}/v1/intention/",
                headers=headers,
                json=intention_payload,
            )
            if intention_resp.is_error:
                detail = intention_resp.text
                try:
                    detail = intention_resp.json().get("detail", detail)
                except Exception:
                    pass
                logger.error("Paymob intention failed (%s): %s", intention_resp.status_code, str(detail)[:500])
                raise ValueError(
                    f"Paymob intention failed ({intention_resp.status_code}): {detail}"
                ) from None
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
