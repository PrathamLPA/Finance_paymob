"""Tests for catalog price gate + automatic Bitrix Estimate creation."""

from decimal import Decimal

import pytest

from app.config import get_settings
from app.integrations.factory import get_bitrix_client
from app.services.estimate_price_gate import evaluate_price_gate
from app.services.workflow_orchestrator import WorkflowOrchestrator


def test_evaluate_price_gate_blocks_below_catalog_min():
    rows = [
        {
            "productId": 10,
            "productName": "AWS Solutions Architect",
            "price": 5500,
            "quantity": 1,
            "taxRate": 0,
            "taxIncluded": "Y",
        }
    ]
    catalog = {10: Decimal("6000.00")}
    result = evaluate_price_gate(rows, catalog)
    assert result.ok is False
    assert "below the catalog minimum" in result.reason.lower()


def test_evaluate_price_gate_passes_at_or_above_min():
    rows = [
        {
            "productId": 10,
            "productName": "AWS Solutions Architect",
            "price": 6000,
            "quantity": 1,
            "taxRate": 5,
            "taxIncluded": "N",
        }
    ]
    catalog = {10: Decimal("6000.00")}
    result = evaluate_price_gate(rows, catalog)
    assert result.ok is True
    assert result.total_payable == Decimal("6300.00")
    assert result.tax_total == Decimal("300.00")


def test_evaluate_price_gate_requires_products():
    result = evaluate_price_gate([], {})
    assert result.ok is False
    assert "no products" in result.reason.lower()


@pytest.mark.asyncio
async def test_price_gate_blocks_and_comments(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(501, email="gate@test.com", name="Gate Test", amount=Decimal("5500"))
    bitrix.seed_catalog_product(10, name="AWS Solutions Architect", price=Decimal("6000"))
    bitrix.seed_lead_products(
        501,
        [
            {
                "productId": 10,
                "productName": "AWS Solutions Architect",
                "price": 5500,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(ValueError, match="below the catalog minimum"):
        await orchestrator.initiate_payment_from_lead(501)

    comments = bitrix._mock_comments.get(("LEAD", 501), [])
    assert comments
    assert "BELOW MINIMUM" in comments[-1]["COMMENT"]


@pytest.mark.asyncio
async def test_price_gate_creates_estimate_and_payment_link(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(502, email="ok@test.com", name="Ok Test", amount=Decimal("6000"))
    bitrix.seed_catalog_product(10, name="AWS Solutions Architect", price=Decimal("6000"))
    bitrix.seed_lead_products(
        502,
        [
            {
                "productId": 10,
                "productName": "AWS Solutions Architect",
                "price": 6500,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    session = await orchestrator.initiate_payment_from_lead(502)

    workflow = orchestrator.get_or_create_workflow(502)
    assert workflow.bitrix_estimate_id is not None
    assert workflow.total_amount == Decimal("6500.00")
    assert session.token
    assert workflow.bitrix_estimate_id in bitrix._mock_estimates

    comments = bitrix._mock_comments.get(("LEAD", 502), [])
    assert any("Estimate #" in c["COMMENT"] for c in comments)
    assert any("Payment link:" in c["COMMENT"] for c in comments)
