"""Tabby / Tamara payment modes are charged through Paymob when BNPL_CHECKOUT_VIA_PAYMOB is on."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import CHANNEL_ONLINE
from app.services.payment_mode import (
    paymob_methods_for_customer_mode,
    resolve_is_tabby_payment_mode,
    resolve_is_tamara_payment_mode,
    resolve_paymob_payment_method_ids,
)
from app.services.payment_session_service import PaymentSessionService


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
        public_base_url="http://api.test",
        payment_frontend_base_url="http://frontend.test",
        bitrix_price_gate_enabled=False,
    )
    base.update(kwargs)
    return Settings(**base)


def test_via_paymob_is_the_default():
    assert _settings().bnpl_checkout_via_paymob is True


def test_paymob_methods_use_the_tabby_and_tamara_integrations():
    settings = _settings()
    assert resolve_paymob_payment_method_ids(
        {"UF_MODE_1": "5782"}, installment_number=1, settings=settings
    ) == [52169]
    assert resolve_paymob_payment_method_ids(
        {"UF_MODE_1": "5784"}, installment_number=1, settings=settings
    ) == [52266]
    assert paymob_methods_for_customer_mode("tamara", settings) == [52266]


@pytest.mark.asyncio
async def test_direct_mode_checks_answer_no_when_via_paymob():
    bitrix = MagicMock()
    lead = {"UF_MODE_1": "5784"}
    for resolver in (resolve_is_tabby_payment_mode, resolve_is_tamara_payment_mode):
        assert not await resolver(
            lead, installment_number=1, settings=_settings(), bitrix=bitrix
        )
    bitrix.assert_not_called()


@pytest.mark.asyncio
async def test_direct_mode_still_available_when_switched_off():
    settings = _settings(bnpl_checkout_via_paymob=False)
    with patch(
        "app.services.payment_mode._load_payment_mode_bitrix_labels",
        new_callable=AsyncMock,
        return_value={"5784": "tamara"},
    ):
        assert await resolve_is_tamara_payment_mode(
            {"UF_MODE_1": "5784"},
            installment_number=1,
            settings=settings,
            bitrix=MagicMock(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("enum_id", ["5782", "5784"])
async def test_create_session_uses_paymob_for_tabby_and_tamara(db_session, enum_id):
    workflow = CustomerWorkflow(
        bitrix_lead_id=9300 + int(enum_id[-1]),
        customer_name="Buyer",
        customer_email="buyer@learnerspoint.org",
        customer_phone="+971500000001",
        total_amount=Decimal("100.00"),
        currency="AED",
        bitrix_lead_payload={"UF_MODE_1": enum_id},
    )
    db_session.add(workflow)
    db_session.commit()

    service = PaymentSessionService(db_session, _settings())
    paymob_session = SimpleNamespace(
        session_id="pm_123", checkout_url="https://accept.paymob.com/unifiedcheckout/x"
    )
    with patch.object(
        service,
        "_create_paymob_session",
        new_callable=AsyncMock,
        return_value=paymob_session,
    ) as paymob_mock:
        session = await service.create_session(
            workflow,
            source_type="lead",
            source_id=workflow.bitrix_lead_id,
            charge_amount=Decimal("100.00"),
            channel=CHANNEL_ONLINE,
        )

    paymob_mock.assert_awaited_once()
    assert session.paymob_checkout_url == paymob_session.checkout_url
    assert session.tabby_payment_id is None
    assert session.tamara_order_id is None
