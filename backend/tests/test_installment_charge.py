"""Tests for first-payment charge resolution from Bitrix installment fields."""

from decimal import Decimal

from app.services.installment_charge import (
    CHARGE_SOURCE_FULL,
    CHARGE_SOURCE_INSTALLMENT_1,
    resolve_first_charge,
)


def test_empty_installment_fields_charge_full_amount():
    plan = resolve_first_charge(
        {"UF_CRM_INSTALLMENT_1": "", "UF_CRM_INSTALLMENT_COUNT": ""},
        remaining_balance=Decimal("5500.00"),
        installment_1_field="UF_CRM_INSTALLMENT_1",
        installment_count_field="UF_CRM_INSTALLMENT_COUNT",
    )
    assert plan.source == CHARGE_SOURCE_FULL
    assert plan.amount == Decimal("5500.00")
    assert plan.locked is True
    assert plan.label == "Full payment"


def test_installment_1_sets_locked_first_payment():
    plan = resolve_first_charge(
        {
            "UF_CRM_INSTALLMENT_1": "1500.50",
            "UF_CRM_INSTALLMENT_COUNT": "3",
        },
        remaining_balance=Decimal("5500.00"),
        installment_1_field="UF_CRM_INSTALLMENT_1",
        installment_count_field="UF_CRM_INSTALLMENT_COUNT",
    )
    assert plan.source == CHARGE_SOURCE_INSTALLMENT_1
    assert plan.amount == Decimal("1500.50")
    assert plan.installment_count == 3
    assert plan.locked is True
    assert plan.label == "Installment 1"


def test_installment_1_is_capped_at_remaining_balance():
    plan = resolve_first_charge(
        {"UF_CRM_INSTALLMENT_1": "9000"},
        remaining_balance=Decimal("5500.00"),
        installment_1_field="UF_CRM_INSTALLMENT_1",
    )
    assert plan.amount == Decimal("5500.00")
    assert plan.source == CHARGE_SOURCE_INSTALLMENT_1


def test_missing_field_codes_default_to_full():
    plan = resolve_first_charge(
        {"UF_CRM_INSTALLMENT_1": "1000"},
        remaining_balance=Decimal("5500.00"),
        installment_1_field="",
    )
    assert plan.source == CHARGE_SOURCE_FULL
    assert plan.amount == Decimal("5500.00")
