"""Tests for Paymob HMAC and payload parsing."""

import hashlib
import hmac
from decimal import Decimal

from app.config import Settings
from app.integrations.paymob import MockPaymobClient, build_mock_paymob_payload, build_transaction_hmac_concat


def _build_hmac(obj: dict, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        build_transaction_hmac_concat(obj).encode(),
        hashlib.sha512,
    ).hexdigest()


def test_paymob_hmac_valid():
    obj = build_mock_paymob_payload(
        transaction_id=999,
        amount_cents=500000,
        currency="AED",
        merchant_order_id="WF-1-abc",
        order_id=555,
    )["obj"]
    secret = "test_hmac_secret"
    signature = _build_hmac(obj, secret)
    client = MockPaymobClient(Settings(use_mock_integrations=False, paymob_hmac_secret=secret))
    assert client.verify_webhook({"obj": obj}, signature) is True


def test_parse_paymob_payload_fields():
    payload = build_mock_paymob_payload(
        transaction_id=12345,
        amount_cents=25000,
        currency="AED",
        merchant_order_id="WF-2-ref",
        order_id=77,
    )
    client = MockPaymobClient()
    data = client.parse_successful_payment(payload)
    assert data is not None
    assert data.transaction_id == "12345"
    assert data.amount == Decimal("250.00")
    assert data.amount_cents == 25000
    assert data.merchant_reference == "WF-2-ref"
    assert data.source_sub_type == "MasterCard"
    assert data.is_3d_secure is True
