"""Direct Tamara checkout when Bitrix Payment Mode is Tamara."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.integrations.tamara import MockTamaraClient
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import CHANNEL_ONLINE, SESSION_COMPLETED, PaymentSession
from app.services.payment_mode import is_tamara_payment_mode
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
        tamara_api_token="",
        tamara_notification_token="notif-secret",
        tamara_base_url="https://api-sandbox.tamara.co",
        public_base_url="http://api.test",
        payment_frontend_base_url="http://frontend.test",
        bitrix_price_gate_enabled=False,
    )
    base.update(kwargs)
    return Settings(**base)


def _expires() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=24)


def test_is_tamara_payment_mode_for_enum_5784():
    settings = _settings()
    assert is_tamara_payment_mode(
        {"UF_MODE_1": "5784"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"5784": "tamara"},
    )
    assert not is_tamara_payment_mode(
        {"UF_MODE_1": "5782"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"5782": "tabby"},
    )


@pytest.mark.asyncio
async def test_create_session_skips_paymob_for_tamara(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9101,
        customer_name="Tamara User",
        customer_email="customer@learnerspoint.org",
        customer_phone="+971500000001",
        total_amount=Decimal("100.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5784"},
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
            source_id=9101,
            charge_amount=Decimal("100.00"),
            channel=CHANNEL_ONLINE,
        )
    paymob_mock.assert_not_called()
    assert session.paymob_checkout_url is None
    assert session.tamara_order_id is None


@pytest.mark.asyncio
async def test_refresh_tamara_checkout_sets_order_id(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9103,
        customer_name="Tamara User",
        customer_email="customer@learnerspoint.org",
        customer_phone="+971500000001",
        total_amount=Decimal("250.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5784"},
    )
    db_session.add(workflow)
    db_session.commit()

    service = PaymentSessionService(db_session, settings)
    session = PaymentSession(
        workflow_id=workflow.id,
        token="tok_tamara_1",
        source_type="lead",
        source_id=9103,
        charge_amount=Decimal("250.00"),
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-old-ref",
        status="terms_accepted",
        expires_at=_expires(),
    )
    db_session.add(session)
    db_session.commit()

    url = await service.refresh_tamara_checkout(session, amount=Decimal("250.00"))
    db_session.refresh(session)
    assert url
    assert session.tamara_order_id
    assert session.merchant_reference.startswith("WF-")
    assert session.paymob_checkout_url == url


@pytest.mark.asyncio
async def test_tamara_webhook_approved_authorises_captures_credits(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9104,
        customer_name="Tamara User",
        customer_email="customer@learnerspoint.org",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5784"},
    )
    db_session.add(workflow)
    db_session.commit()

    order_id = "11111111-2222-3333-4444-555555555555"
    session = PaymentSession(
        workflow_id=workflow.id,
        token="tok_tamara_wh",
        source_type="lead",
        source_id=9104,
        charge_amount=Decimal("100.00"),
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-9104-abcd1234",
        tamara_order_id=order_id,
        status="terms_accepted",
        expires_at=_expires(),
    )
    db_session.add(session)
    db_session.commit()

    payload = {
        "order_id": order_id,
        "order_reference_id": "WF-9104-abcd1234",
        "event_type": "order_approved",
        "data": [],
    }

    orch = WorkflowOrchestrator(db_session, settings)
    with (
        patch.object(
            orch.tamara,
            "authorise_order",
            new_callable=AsyncMock,
            return_value={"order_id": order_id, "status": "authorised", "auto_captured": False},
        ) as auth_mock,
        patch.object(
            orch.tamara,
            "capture_order",
            new_callable=AsyncMock,
            return_value={"order_id": order_id, "status": "fully_captured"},
        ) as capture_mock,
        patch.object(
            orch,
            "apply_recorded_payment",
            new_callable=AsyncMock,
            side_effect=lambda workflow, *a, **k: workflow,
        ),
    ):
        result = await orch.handle_tamara_webhook(
            payload, auth_token="notif-secret"
        )

    assert result is not None
    auth_mock.assert_awaited_once()
    capture_mock.assert_awaited_once()
    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("100.00")
    db_session.refresh(session)
    assert session.status == SESSION_COMPLETED


def test_mock_tamara_verify_token():
    client = MockTamaraClient(
        _settings(
            tamara_notification_token="secret",
            use_mock_integrations=False,
        )
    )
    assert client.verify_webhook_token("secret")
    assert not client.verify_webhook_token("nope")


@pytest.mark.asyncio
async def test_accept_terms_tamara_calls_tamara_not_paymob(db_session):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=9105,
        customer_name="Buyer",
        customer_email="buyer@learnerspoint.org",
        customer_phone="+971500000001",
        total_amount=Decimal("80.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": "5784"},
    )
    db_session.add(workflow)
    db_session.commit()

    import secrets

    session = PaymentSession(
        workflow_id=workflow.id,
        token=secrets.token_urlsafe(16),
        source_type="lead",
        source_id=9105,
        charge_amount=Decimal("80.00"),
        currency="AED",
        channel=CHANNEL_ONLINE,
        merchant_reference="WF-9105-init",
        status="pending",
        expires_at=_expires(),
    )
    db_session.add(session)
    db_session.commit()

    terms = TermsService(db_session, settings)
    with (
        patch.object(
            terms.session_service,
            "refresh_tamara_checkout",
            new_callable=AsyncMock,
            return_value="https://checkout.tamara.co/mock",
        ) as tamara_refresh,
        patch.object(
            terms.session_service,
            "refresh_paymob_checkout",
            new_callable=AsyncMock,
        ) as paymob_refresh,
        patch.object(
            terms.session_service,
            "refresh_tabby_checkout",
            new_callable=AsyncMock,
        ) as tabby_refresh,
        patch(
            "app.services.payment_mode.resolve_session_channel_from_bitrix",
            new_callable=AsyncMock,
            return_value=CHANNEL_ONLINE,
        ),
        patch(
            "app.services.payment_mode.resolve_is_tabby_payment_mode",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "app.services.payment_mode.resolve_is_tamara_payment_mode",
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

    assert url == "https://checkout.tamara.co/mock"
    tamara_refresh.assert_awaited_once()
    paymob_refresh.assert_not_called()
    tabby_refresh.assert_not_called()
