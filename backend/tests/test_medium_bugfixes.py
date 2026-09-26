"""Regression tests for Medium audit fixes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import Settings, get_settings
from app.integrations.base import PaymentWebhookData
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import (
    CHANNEL_ONLINE,
    SESSION_TERMS_ACCEPTED,
    SOURCE_LEAD,
    PaymentSession,
)
from app.models.payment_transaction import PaymentTransaction
from app.services.payment_mode import (
    is_tabby_payment_mode,
    paymob_methods_for_customer_mode,
    resolve_paymob_payment_method_ids,
)
from app.services.workflow_orchestrator import WorkflowOrchestrator


@pytest.mark.asyncio
async def test_paymob_fail_then_success_same_txn_id_credits(db_session):
    workflow = CustomerWorkflow(
        bitrix_lead_id=910001,
        customer_name="Fail Then OK",
        customer_email="failok@example.com",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
    )
    db_session.add(workflow)
    db_session.flush()
    session = PaymentSession(
        workflow_id=workflow.id,
        token="fail-ok-token",
        source_type=SOURCE_LEAD,
        source_id=910001,
        charge_amount=Decimal("50.00"),
        charge_source="installment_1",
        amount_locked=True,
        installment_number=1,
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-FAIL-OK-1",
        status=SESSION_TERMS_ACCEPTED,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()

    failed = PaymentWebhookData(
        transaction_id="paymob-txn-shared-1",
        order_id="ord-1",
        amount=Decimal("50.00"),
        currency="AED",
        merchant_reference="WF-FAIL-OK-1",
        success=False,
        raw_payload="{}",
    )
    orch = WorkflowOrchestrator(db_session, get_settings())
    await orch.handle_failed_payment(failed)
    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("0.00")
    txn = db_session.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.transaction_id == "paymob-txn-shared-1"
        )
    )
    assert txn is not None
    assert txn.status == "failed"

    success = PaymentWebhookData(
        transaction_id="paymob-txn-shared-1",
        order_id="ord-1",
        amount=Decimal("50.00"),
        currency="AED",
        merchant_reference="WF-FAIL-OK-1",
        success=True,
        raw_payload="{}",
    )
    result = await orch.handle_paymob_webhook(success)
    assert result is not None
    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("50.00")
    db_session.refresh(txn)
    assert txn.status == "success"
    assert txn.success is True


def test_truncated_enum_map_still_resolves_tabby():
    """Railway map missing 5782 must not demote Tabby → card."""
    settings = Settings(
        paymob_integration_id_card=49586,
        paymob_integration_id_tabby=52169,
        paymob_integration_id_tamara=52266,
        bitrix_field_payment_1_mode="UF_MODE_1",
        # Truncated map — no 5782/5784
        bitrix_payment_mode_enum_map="5774:cash,13156:card",
    )
    lead = {"UF_MODE_1": "5782"}
    assert is_tabby_payment_mode(
        lead, installment_number=1, settings=settings
    )
    methods = resolve_paymob_payment_method_ids(
        lead, installment_number=1, settings=settings
    )
    assert methods == [52169]


def test_tabby_mode_with_zero_integration_raises():
    settings = Settings(
        paymob_integration_id_card=49586,
        paymob_integration_id_tabby=0,
        paymob_integration_id_tamara=0,
        bitrix_field_payment_1_mode="UF_MODE_1",
        bitrix_payment_mode_enum_map="5782:tabby,5784:tamara,13156:card",
    )
    with pytest.raises(ValueError, match="PAYMOB_INTEGRATION_ID_TABBY"):
        resolve_paymob_payment_method_ids(
            {"UF_MODE_1": "5782"},
            installment_number=1,
            settings=settings,
        )
    with pytest.raises(ValueError, match="PAYMOB_INTEGRATION_ID_TABBY"):
        paymob_methods_for_customer_mode("tabby", settings)


def test_bitrix_webhook_rejects_empty_secret_in_production(client, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BITRIX_WEBHOOK_SECRET", "")
    monkeypatch.setenv("USE_MOCK_INTEGRATIONS", "true")
    get_settings.cache_clear()

    resp = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "1"},
    )
    assert resp.status_code == 503
    assert "BITRIX_WEBHOOK_SECRET" in resp.json()["detail"]
    get_settings.cache_clear()
