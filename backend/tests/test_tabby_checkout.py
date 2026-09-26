"""Direct Tabby checkout when Bitrix Payment Mode is Tabby."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.integrations.tabby import MockTabbyClient
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import CHANNEL_ONLINE, SESSION_COMPLETED, PaymentSession
from app.services.payment_mode import is_tabby_payment_mode
from app.services.payment_session_service import PaymentSessionService
from app.services.terms_service import TermsService
from app.services.workflow_orchestrator import WorkflowOrchestrator


def _settings(**kwargs) -> Settings:
    base = dict(
        use_mock_integrations=True,
        paymob_integration_id=49586,
        paymob_integration_id_card=49586,
        paymob_integration_id_tabby=52169,
        paymob_integration_id_tamara=52266,
        bitrix_field_payment_1_mode="UF_MODE_1",
        bitrix_payment_mode_enum_map=(
            "5774:cash,5776:website_payment,13156:card,5782:tabby,"
            "5784:tamara,5778:bank_transfer"
        ),
        tabby_secret_key="",
        tabby_merchant_code="test_merchant",
        tabby_webhook_auth_value="test-secret",
        tabby_webhook_auth_header="X-Tabby-Auth",
        public_base_url="http://api.test",
        payment_frontend_base_url="http://frontend.test",
        bitrix_price_gate_enabled=False,
    )
    base.update(kwargs)
    return Settings(**base)


def _expires() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=24)


def test_is_tabby_payment_mode_for_enum_5782():
    settings = _settings()
    assert is_tabby_payment_mode(
        {"UF_MODE_1": "5782"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"5782": "tabby"},
    )
    assert not is_tabby_payment_mode(
        {"UF_MODE_1": "13156"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"13156": "card"},
    )
    assert not is_tabby_payment_mode(
        {"UF_MODE_1": "5776"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"5776": "website payment"},
    )


@pytest.mark.asyncio
async def test_create_session_skips_paymob_for_tabby(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9001,
        customer_name="Tabby User",
        customer_email="otp.success@tabby.ai",
        customer_phone="+971500000001",
        total_amount=Decimal("100.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5782"},
    )
    db_session.add(workflow)
    db_session.commit()

    service = PaymentSessionService(db_session, settings)
    with patch.object(
        service, "_create_paymob_session", new_callable=AsyncMock
    ) as paymob_mock:
        session = await service.create_session(
            workflow,
            source_type="lead",
            source_id=9001,
            charge_amount=Decimal("100.00"),
            channel=CHANNEL_ONLINE,
        )
    paymob_mock.assert_not_called()
    assert session.paymob_checkout_url is None
    assert session.tabby_payment_id is None


@pytest.mark.asyncio
async def test_create_session_uses_paymob_for_card(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9002,
        customer_name="Card User",
        customer_email="card@example.com",
        total_amount=Decimal("100.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "13156"},
    )
    db_session.add(workflow)
    db_session.commit()

    service = PaymentSessionService(db_session, settings)
    session = await service.create_session(
        workflow,
        source_type="lead",
        source_id=9002,
        charge_amount=Decimal("100.00"),
        channel=CHANNEL_ONLINE,
    )
    assert session.paymob_checkout_url
    assert session.tabby_payment_id is None


@pytest.mark.asyncio
async def test_refresh_tabby_checkout_sets_payment_id(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9003,
        customer_name="Tabby User",
        customer_email="otp.success@tabby.ai",
        customer_phone="+971500000001",
        total_amount=Decimal("250.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5782"},
    )
    db_session.add(workflow)
    db_session.commit()

    service = PaymentSessionService(db_session, settings)
    session = PaymentSession(
        workflow_id=workflow.id,
        token="tok_tabby_1",
        source_type="lead",
        source_id=9003,
        charge_amount=Decimal("250.00"),
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-old-ref",
        status="terms_accepted",
        expires_at=_expires(),
    )
    db_session.add(session)
    db_session.commit()

    url = await service.refresh_tabby_checkout(session, amount=Decimal("250.00"))
    db_session.refresh(session)
    assert url
    assert session.tabby_payment_id
    assert session.tabby_payment_id.startswith("tabby_")
    assert session.merchant_reference.startswith("WF-")
    assert session.paymob_checkout_url == url


@pytest.mark.asyncio
async def test_tabby_webhook_authorized_captures_and_credits(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9004,
        customer_name="Tabby User",
        customer_email="otp.success@tabby.ai",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5782"},
    )
    db_session.add(workflow)
    db_session.commit()

    session = PaymentSession(
        workflow_id=workflow.id,
        token="tok_tabby_wh",
        source_type="lead",
        source_id=9004,
        charge_amount=Decimal("100.00"),
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-9004-abcd1234",
        tabby_payment_id="tabby_pay_abc",
        status="terms_accepted",
        expires_at=_expires(),
    )
    db_session.add(session)
    db_session.commit()

    payload = {
        "id": "tabby_pay_abc",
        "status": "authorized",
        "amount": "100.00",
        "currency": "AED",
        "order": {"reference_id": "WF-9004-abcd1234"},
        "captures": [],
    }

    orch = WorkflowOrchestrator(db_session, settings)
    with (
        patch.object(
            orch.tabby,
            "get_payment",
            new_callable=AsyncMock,
            return_value={"id": "tabby_pay_abc", "status": "AUTHORIZED"},
        ),
        patch.object(
            orch.tabby,
            "capture_payment",
            new_callable=AsyncMock,
            return_value={"id": "tabby_pay_abc", "status": "CLOSED"},
        ) as capture_mock,
        patch.object(
            orch,
            "apply_recorded_payment",
            new_callable=AsyncMock,
            side_effect=lambda workflow, *a, **k: workflow,
        ),
    ):
        result = await orch.handle_tabby_webhook(payload, auth_header="test-secret")

    assert result is not None
    capture_mock.assert_awaited_once()
    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("100.00")
    db_session.refresh(session)
    assert session.status == SESSION_COMPLETED


def test_mock_tabby_verify_auth():
    client = MockTabbyClient(
        _settings(tabby_webhook_auth_value="secret", use_mock_integrations=False)
    )
    assert client.verify_webhook_auth("secret")
    assert not client.verify_webhook_auth("nope")


@pytest.mark.asyncio
async def test_accept_terms_tabby_calls_tabby_not_paymob(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9005,
        customer_name="Buyer",
        customer_email="buyer@learnerspoint.org",
        customer_phone="+971500000001",
        total_amount=Decimal("80.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5782"},
    )
    db_session.add(workflow)
    db_session.commit()

    import secrets

    session = PaymentSession(
        workflow_id=workflow.id,
        token=secrets.token_urlsafe(16),
        source_type="lead",
        source_id=9005,
        charge_amount=Decimal("80.00"),
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-9005-init",
        status="pending",
        expires_at=_expires(),
    )
    db_session.add(session)
    db_session.commit()

    terms = TermsService(db_session, settings)
    with (
        patch.object(
            terms.session_service,
            "refresh_tabby_checkout",
            new_callable=AsyncMock,
            return_value="https://checkout.tabby.ai/mock",
        ) as tabby_refresh,
        patch.object(
            terms.session_service,
            "refresh_paymob_checkout",
            new_callable=AsyncMock,
        ) as paymob_refresh,
        patch(
            "app.services.payment_mode.resolve_session_channel_from_bitrix",
            new_callable=AsyncMock,
            return_value=CHANNEL_ONLINE,
        ),
        patch(
            "app.services.payment_mode.resolve_is_tabby_payment_mode",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.services.terms_service.load_lead_courses",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        url = await terms.accept_terms(
            session.token,
            accepted=True,
            ip_address="127.0.0.1",
            course_for="self",
            registrant_name="Buyer",
            registrant_email="buyer@learnerspoint.org",
            registrant_phone="+971500000001",
            payment_amount=Decimal("80.00"),
        )

    assert url == "https://checkout.tabby.ai/mock"
    tabby_refresh.assert_awaited_once()
    paymob_refresh.assert_not_called()
