"""Paymob integration — aligned with developers.paymob.com webhook spec."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from collections.abc import Iterator
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


def _bool_str(value: Any, *, style: str = "lower") -> str:
    if isinstance(value, bool):
        return str(value).lower() if style == "lower" else str(value)
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


def build_transaction_hmac_concat(
    obj: dict[str, Any],
    *,
    bool_style: str = "lower",
    created_at: str | None = None,
) -> str:
    values = [
        obj.get("amount_cents", ""),
        obj.get("created_at", "") if created_at is None else created_at,
        obj.get("currency", ""),
        _bool_str(obj.get("error_occured", False), style=bool_style),
        _bool_str(obj.get("has_parent_transaction", False), style=bool_style),
        obj.get("id", ""),
        obj.get("integration_id", ""),
        _bool_str(obj.get("is_3d_secure", False), style=bool_style),
        _bool_str(obj.get("is_auth", False), style=bool_style),
        _bool_str(obj.get("is_capture", False), style=bool_style),
        _bool_str(obj.get("is_refunded", False), style=bool_style),
        _bool_str(obj.get("is_standalone_payment", True), style=bool_style),
        _bool_str(obj.get("is_voided", False), style=bool_style),
        extract_order_id(obj),
        obj.get("owner", ""),
        _bool_str(obj.get("pending", False), style=bool_style),
        extract_source_field(obj, "pan"),
        extract_source_field(obj, "sub_type"),
        extract_source_field(obj, "type"),
        _bool_str(obj.get("success", False), style=bool_style),
    ]
    return "".join(str(v) for v in values)


def _created_at_variants(value: str) -> list[tuple[str, str]]:
    """Paymob signs created_at as it serialises it, which varies by region."""
    variants = [("raw", value)]
    without_tz = re.sub(r"(?:Z|[+-]\d{2}:?\d{2})$", "", value)
    if without_tz != value:
        variants.append(("no_tz", without_tz))
    for name, candidate in list(variants):
        if "T" in candidate:
            variants.append((f"{name}_space", candidate.replace("T", " ", 1)))
    return variants


def iter_hmac_candidates(obj: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield (label, concat) pairs, documented spelling first."""
    created = str(obj.get("created_at", "") or "")
    for created_label, created_value in _created_at_variants(created):
        for bool_style in ("lower", "python"):
            label = f"created={created_label},bool={bool_style}"
            yield label, build_transaction_hmac_concat(
                obj, bool_style=bool_style, created_at=created_value
            )


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
        received = str(signature).strip().lower()
        secret = self.settings.paymob_hmac_secret.encode()

        concat = ""
        calculated = ""
        tried = 0
        for label, candidate in iter_hmac_candidates(obj):
            digest = hmac.new(secret, candidate.encode(), hashlib.sha512).hexdigest()
            if tried == 0:
                concat, calculated = candidate, digest
            tried += 1
            if not hmac.compare_digest(digest, received):
                continue
            if tried == 1:
                logger.info(
                    "Paymob HMAC verified | txn=%s integration_id=%s",
                    obj.get("id") or "-",
                    obj.get("integration_id") or "-",
                )
            else:
                logger.warning(
                    "Paymob HMAC verified via non-standard field format | txn=%s "
                    "variant=%s action=make_this_variant_the_default",
                    obj.get("id") or "-",
                    label,
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
            "variants_tried=%s signature_len=%s calculated=%s… received=%s… "
            "secret_len=%s secret_fingerprint=%s",
            obj.get("id") or "-",
            likely_cause,
            payload_shape,
            order_shape,
            source_shape,
            missing_fields or "none",
            tried,
            len(received),
            calculated[:16],
            received[:16],
            len(self.settings.paymob_hmac_secret),
            secret_fingerprint,
        )
        # No secret and only a masked PAN, so the signed string is safe to log.
        logger.warning(
            "Paymob HMAC signed string | txn=%s concat=%r keys=%s",
            obj.get("id") or "-",
            concat,
            sorted(obj.keys()),
        )
        if self.settings.log_paymob_payloads:
            # Opt-in: contains customer billing details, so keep it off by default.
            logger.warning(
                "Paymob HMAC transaction dump | txn=%s transaction=%s",
                obj.get("id") or "-",
                json.dumps(obj, default=str)[:6000],
            )
        return False

    async def authenticate_webhook(
        self, payload: dict[str, Any], signature: str | None
    ) -> bool:
        """Prefer documented HMAC; fall back to Transaction Inquiry when enabled."""
        if self.verify_webhook(payload, signature):
            return True

        if not self.settings.paymob_hmac_fallback_to_inquiry:
            return False

        obj = extract_transaction_obj(payload)
        txn_id = obj.get("id")
        if txn_id is None:
            logger.warning("Paymob inquiry fallback skipped reason=missing_transaction_id")
            return False

        try:
            remote = await self.fetch_transaction(str(txn_id))
        except Exception:
            logger.exception(
                "Paymob inquiry fallback failed | txn=%s", txn_id
            )
            return False

        if not remote:
            logger.warning(
                "Paymob inquiry fallback rejected | txn=%s reason=not_found", txn_id
            )
            return False

        if not self._callback_matches_remote_transaction(obj, remote):
            logger.warning(
                "Paymob inquiry fallback rejected | txn=%s reason=callback_mismatch",
                txn_id,
            )
            return False

        logger.warning(
            "TEMPORARY Paymob HMAC bypassed via Transaction Inquiry | txn=%s "
            "success=%s pending=%s action=restore_hmac_once_paymob_documents_intention_hmac",
            txn_id,
            remote.get("success"),
            remote.get("pending"),
        )
        return True

    async def fetch_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        """Look up a transaction on Paymob (API Key → auth token → inquiry)."""
        if self.settings.use_mock_integrations:
            return None
        if not self.settings.paymob_api_key:
            logger.error(
                "Paymob inquiry unavailable reason=api_key_not_configured "
                "action=set_PAYMOB_API_KEY"
            )
            return None

        base = self.settings.paymob_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_resp = await client.post(
                f"{base}/api/auth/tokens",
                json={"api_key": self.settings.paymob_api_key},
            )
            if token_resp.is_error:
                logger.error(
                    "Paymob auth token failed (%s): %s",
                    token_resp.status_code,
                    token_resp.text[:300],
                )
                return None
            token = token_resp.json().get("token")
            if not token:
                logger.error("Paymob auth token response missing token field")
                return None

            txn_resp = await client.get(
                f"{base}/api/acceptance/transactions/{transaction_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if txn_resp.is_error:
                logger.error(
                    "Paymob transaction inquiry failed (%s): %s",
                    txn_resp.status_code,
                    txn_resp.text[:300],
                )
                return None
            data = txn_resp.json()
            return data if isinstance(data, dict) else None

    @staticmethod
    def _callback_matches_remote_transaction(
        callback: dict[str, Any], remote: dict[str, Any]
    ) -> bool:
        """Require Paymob's stored transaction to match the webhook's core fields."""
        try:
            same_id = str(callback.get("id")) == str(remote.get("id"))
            same_amount = int(callback.get("amount_cents") or 0) == int(
                remote.get("amount_cents") or 0
            )
            same_currency = str(callback.get("currency") or "") == str(
                remote.get("currency") or ""
            )
            same_integration = str(callback.get("integration_id") or "") == str(
                remote.get("integration_id") or ""
            )
            remote_success = remote.get("success") is True or str(
                remote.get("success")
            ).lower() == "true"
            remote_pending = remote.get("pending") is True or str(
                remote.get("pending")
            ).lower() == "true"
        except (TypeError, ValueError):
            return False

        return (
            same_id
            and same_amount
            and same_currency
            and same_integration
            and remote_success
            and not remote_pending
        )

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
