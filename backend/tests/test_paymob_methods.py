"""Paymob Card / Tabby / Tamara method selection from Bitrix payment mode."""

import pytest

from app.config import Settings
from app.services.payment_mode import (
    bitrix_enum_id_for_customer_mode,
    channel_for_customer_payment_mode,
    paymob_methods_for_customer_mode,
    resolve_paymob_payment_method_ids,
    validate_customer_payment_mode,
)


def _settings() -> Settings:
    return Settings(
        paymob_integration_id=49586,
        paymob_integration_id_card=49586,
        paymob_integration_id_tabby=52169,
        paymob_integration_id_tamara=52266,
        bitrix_field_payment_1_mode="UF_MODE_1",
        bitrix_payment_mode_enum_map=(
            "5774:cash,5776:website_payment,13156:card,5782:tabby,5784:tamara,5778:bank_transfer"
        ),
    )


def test_tabby_mode_uses_tabby_integration_only():
    lead = {"UF_MODE_1": "5782"}
    methods = resolve_paymob_payment_method_ids(
        lead,
        installment_number=1,
        settings=_settings(),
        bitrix_enum_labels={"5782": "tabby"},
    )
    assert methods == [52169]


def test_tamara_mode_uses_tamara_integration_only():
    lead = {"UF_MODE_1": "5784"}
    methods = resolve_paymob_payment_method_ids(
        lead,
        installment_number=1,
        settings=_settings(),
        bitrix_enum_labels={"5784": "tamara"},
    )
    assert methods == [52266]


def test_website_payment_offers_card_tabby_tamara():
    lead = {"UF_MODE_1": "5776"}
    methods = resolve_paymob_payment_method_ids(
        lead,
        installment_number=1,
        settings=_settings(),
        bitrix_enum_labels={"5776": "website payment"},
    )
    assert methods == [49586, 52169, 52266]


def test_online_and_card_modes_use_card_only():
    settings = _settings()
    settings.bitrix_payment_mode_enum_map = (
        "5776:website_payment,5788:online,5780:card,5782:tabby"
    )
    online = resolve_paymob_payment_method_ids(
        {"UF_MODE_1": "5788"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"5788": "online"},
    )
    assert online == [49586]
    card = resolve_paymob_payment_method_ids(
        {"UF_MODE_1": "5780"},
        installment_number=1,
        settings=settings,
        bitrix_enum_labels={"5780": "card"},
    )
    assert card == [49586]


def test_default_empty_mode_uses_card():
    methods = resolve_paymob_payment_method_ids(
        {},
        installment_number=1,
        settings=_settings(),
    )
    assert methods == [49586]


def test_validate_customer_payment_mode():
    assert validate_customer_payment_mode("Card") == "card"
    assert validate_customer_payment_mode("website_payment") == "website_payment"
    with pytest.raises(ValueError):
        validate_customer_payment_mode("purchase_order")


def test_customer_mode_paymob_methods():
    settings = _settings()
    assert paymob_methods_for_customer_mode("card", settings) == [49586]
    assert paymob_methods_for_customer_mode("tabby", settings) == [52169]
    assert paymob_methods_for_customer_mode("tamara", settings) == [52266]
    assert paymob_methods_for_customer_mode("website_payment", settings) == [
        49586,
        52169,
        52266,
    ]
    assert paymob_methods_for_customer_mode("cash", settings) == []
    assert paymob_methods_for_customer_mode("bank_transfer", settings) == []


def test_customer_mode_channel_and_bitrix_enum():
    settings = _settings()
    assert channel_for_customer_payment_mode("card") == "online"
    assert channel_for_customer_payment_mode("cash") == "cash"
    assert channel_for_customer_payment_mode("bank_transfer") == "bank_transfer"
    assert bitrix_enum_id_for_customer_mode("card", settings) == "13156"
    assert bitrix_enum_id_for_customer_mode("cash", settings) == "5774"
    assert bitrix_enum_id_for_customer_mode("website_payment", settings) == "5776"
    assert bitrix_enum_id_for_customer_mode("tabby", settings) == "5782"
    assert bitrix_enum_id_for_customer_mode("bank_transfer", settings) == "5778"
