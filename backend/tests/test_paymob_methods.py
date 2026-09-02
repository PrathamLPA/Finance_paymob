"""Paymob Card / Tabby / Tamara method selection from Bitrix payment mode."""

from app.config import Settings
from app.services.payment_mode import resolve_paymob_payment_method_ids


def _settings() -> Settings:
    return Settings(
        paymob_integration_id=49586,
        paymob_integration_id_card=49586,
        paymob_integration_id_tabby=52169,
        paymob_integration_id_tamara=52266,
        bitrix_field_payment_1_mode="UF_MODE_1",
        bitrix_payment_mode_enum_map=(
            "5774:cash,5776:website_payment,5782:tabby,5784:tamara,5778:bank_transfer"
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


def test_default_empty_mode_uses_card():
    methods = resolve_paymob_payment_method_ids(
        {},
        installment_number=1,
        settings=_settings(),
    )
    assert methods == [49586]
