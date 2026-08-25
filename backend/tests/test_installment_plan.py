"""Tests for persisted installment plan capture and first-charge resolution."""

from decimal import Decimal

import pytest

from app.config import Settings, get_settings
from app.integrations.factory import get_bitrix_client
from app.models.customer_workflow import CustomerWorkflow
from app.services.estimate_price_gate import (
    evaluate_price_gate,
    line_money_breakdown,
    serialize_pricing_snapshot,
)
from app.services.installment_plan import (
    backfill_installment_plan_from_payload,
    plan_is_indicated,
    resolve_first_charge_for_workflow,
    validate_installment_plan,
)
from app.services.workflow_orchestrator import WorkflowOrchestrator


def _settings(**overrides) -> Settings:
    get_settings.cache_clear()
    base = {
        "BITRIX_FIELD_INSTALLMENT_COUNT": "UF_COUNT",
        "BITRIX_FIELD_INSTALLMENT_1": "UF_I1",
        "BITRIX_FIELD_INSTALLMENT_2": "UF_I2",
        "BITRIX_FIELD_INSTALLMENT_3": "UF_I3",
        "BITRIX_FIELD_INSTALLMENT_4": "UF_I4",
        "BITRIX_FIELD_INSTALLMENT_1_DATE": "UF_D1",
        "BITRIX_FIELD_INSTALLMENT_2_DUE_DATE": "UF_D2",
        "BITRIX_FIELD_INSTALLMENT_3_DUE_DATE": "UF_D3",
        "BITRIX_FIELD_INSTALLMENT_4_DUE_DATE": "UF_D4",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    for key, value in base.items():
        __import__("os").environ[key] = value
    get_settings.cache_clear()
    return get_settings()


def test_validate_installment_plan_requires_matching_total():
    settings = _settings()
    lead = {
        "UF_COUNT": "3",
        "UF_I1": "1000",
        "UF_D1": "2026-01-01",
        "UF_I2": "1000",
        "UF_D2": "2026-02-01",
        "UF_I3": "1000",
        "UF_D3": "2026-03-01",
    }
    bad = validate_installment_plan(lead, settings, payable_total=Decimal("5500.00"))
    assert bad.indicated is True
    assert bad.ok is False
    assert any("payable total" in err.lower() for err in bad.errors)

    good = validate_installment_plan(lead, settings, payable_total=Decimal("3000.00"))
    assert good.ok is True
    assert len(good.slots) == 3


def test_plan_not_indicated_for_installment_1_only():
    settings = _settings()
    lead = {"UF_I1": "1500"}
    assert plan_is_indicated(lead, settings) is False
    validation = validate_installment_plan(lead, settings, payable_total=Decimal("5500"))
    assert validation.ok is True
    assert validation.indicated is False


def test_inclusive_vat_snapshot_extracts_tax():
    rows = [
        {
            "productId": 10,
            "productName": "Course",
            "price": 1050,
            "quantity": 1,
            "taxRate": 5,
            "taxIncluded": "Y",
        }
    ]
    gate = evaluate_price_gate(rows, {10: Decimal("1000.00")})
    assert gate.total_payable == Decimal("1050.00")
    assert gate.vat_total == Decimal("50.00")
    assert gate.subtotal == Decimal("1000.00")
    # Bitrix estimate tax_value stays 0 when VAT is already included in price.
    assert gate.tax_total == Decimal("0.00")

    snap = serialize_pricing_snapshot(gate.lines, currency="AED", total_payable=gate.total_payable)
    assert snap["vat_total"] == "50.00"
    assert snap["subtotal"] == "1000.00"
    assert snap["total_payable"] == "1050.00"


def test_exclusive_vat_line_breakdown():
    from app.services.estimate_price_gate import ProductLine

    line = ProductLine(
        product_id=1,
        product_name="Course",
        quantity=Decimal("1"),
        selling_price=Decimal("6000.00"),
        tax_rate=Decimal("5.00"),
        tax_included=False,
    )
    subtotal, vat, payable = line_money_breakdown(line)
    assert subtotal == Decimal("6000.00")
    assert vat == Decimal("300.00")
    assert payable == Decimal("6300.00")


@pytest.mark.asyncio
async def test_first_link_persists_valid_plan_and_charges_installment_1(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "false")
    settings = _settings()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(701, email="plan@test.com", name="Plan Test", amount=Decimal("3000"))
    bitrix._mock_leads[701].update(
        {
            settings.bitrix_field_installment_count: "2",
            settings.bitrix_field_installment_1: "1500",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "1500",
            settings.bitrix_field_installment_2_due_date: "2026-01-20",
        }
    )

    orchestrator = WorkflowOrchestrator(db_session)
    session = await orchestrator.initiate_payment_from_lead(701)
    workflow = orchestrator.get_or_create_workflow(701)

    assert len(workflow.installments) == 2
    assert workflow.pricing_snapshot is not None
    assert workflow.pricing_snapshot["total_payable"] == "3000.00"
    assert session.charge_amount == Decimal("1500.00")
    assert session.charge_source == "installment_1"
    assert session.installment_number == 1

    # Frozen: later Bitrix edits must not rewrite the plan.
    bitrix._mock_leads[701][settings.bitrix_field_installment_2] = "500"
    await orchestrator.initiate_payment_from_lead(701, lead_data=bitrix._mock_leads[701])
    db_session.refresh(workflow)
    amounts = [row.amount for row in sorted(workflow.installments, key=lambda r: r.installment_number)]
    assert amounts == [Decimal("1500.00"), Decimal("1500.00")]


@pytest.mark.asyncio
async def test_invalid_indicated_plan_blocks_payment_link(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "false")
    settings = _settings()
    bitrix = get_bitrix_client()
    bitrix.seed_lead(702, email="bad@test.com", name="Bad Plan", amount=Decimal("3000"))
    bitrix._mock_leads[702].update(
        {
            settings.bitrix_field_installment_count: "3",
            settings.bitrix_field_installment_1: "1000",
            # Missing dates / remaining amounts
        }
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(ValueError, match="Installment plan is incomplete"):
        await orchestrator.initiate_payment_from_lead(702)

    comments = bitrix._mock_comments.get(("LEAD", 702), [])
    assert any("Installment plan is incomplete" in c["COMMENT"] for c in comments)


@pytest.mark.asyncio
async def test_full_payment_stores_pricing_snapshot_without_installments(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "false")
    _settings()
    bitrix = get_bitrix_client()
    bitrix.seed_lead(703, email="full@test.com", name="Full Pay", amount=Decimal("4500"))

    orchestrator = WorkflowOrchestrator(db_session)
    session = await orchestrator.initiate_payment_from_lead(703)
    workflow = orchestrator.get_or_create_workflow(703)

    assert workflow.installments == []
    assert workflow.pricing_snapshot["total_payable"] == "4500.00"
    assert session.charge_source == "full"
    assert session.installment_number is None
    assert session.charge_amount == Decimal("4500.00")


def test_backfill_from_lead_payload(db_session, monkeypatch):
    settings = _settings()
    workflow = CustomerWorkflow(
        bitrix_lead_id=800,
        total_amount=Decimal("2000.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
        bitrix_lead_payload={
            settings.bitrix_field_installment_count: "2",
            settings.bitrix_field_installment_1: "1000",
            settings.bitrix_field_installment_1_date: "2026-01-10",
            settings.bitrix_field_installment_2: "1000",
            settings.bitrix_field_installment_2_due_date: "2026-02-10",
        },
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    assert backfill_installment_plan_from_payload(db_session, workflow, settings) is True
    assert len(workflow.installments) == 2
    plan = resolve_first_charge_for_workflow(workflow, lead=None, settings=settings)
    assert plan.amount == Decimal("1000.00")
    assert plan.source == "installment_1"


def test_ordered_dates_required():
    settings = _settings()
    lead = {
        "UF_COUNT": "2",
        "UF_I1": "1000",
        "UF_D1": "2026-03-01",
        "UF_I2": "1000",
        "UF_D2": "2026-02-01",
    }
    result = validate_installment_plan(lead, settings, payable_total=Decimal("2000"))
    assert result.ok is False
    assert any("before installment" in err.lower() for err in result.errors)
