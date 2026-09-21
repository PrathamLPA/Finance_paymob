"""Enrollment type: Batch uses catalog path; One-One forces manager approval."""

from decimal import Decimal

import pytest

from app.config import get_settings
from app.integrations.factory import get_bitrix_client
from app.services.enrollment_type import (
    ONE_ON_ONE_APPROVAL_REASON,
    apply_enrollment_type_to_gate,
    is_batch_enrollment,
    is_one_on_one_enrollment,
)
from app.services.estimate_price_gate import evaluate_price_gate
from app.services.price_approval_service import PriceApprovalPending
from app.services.workflow_orchestrator import WorkflowOrchestrator


def test_enrollment_helpers_read_enum_ids(monkeypatch):
    monkeypatch.setenv("BITRIX_FIELD_ENROLLMENT_TYPE", "UF_CRM_1789736997226")
    monkeypatch.setenv("BITRIX_ENROLLMENT_BATCH_ENUM_IDS", "19702")
    monkeypatch.setenv("BITRIX_ENROLLMENT_ONE_ONE_ENUM_IDS", "19704")
    get_settings.cache_clear()
    settings = get_settings()

    assert is_one_on_one_enrollment(
        {"UF_CRM_1789736997226": "19704"}, settings
    )
    assert is_batch_enrollment({"UF_CRM_1789736997226": "19702"}, settings)
    assert not is_one_on_one_enrollment({"UF_CRM_1789736997226": "19702"}, settings)
    assert not is_one_on_one_enrollment({"UF_CRM_1789736997226": ""}, settings)


def test_apply_enrollment_forces_gate_fail_for_one_one(monkeypatch):
    monkeypatch.setenv("BITRIX_FIELD_ENROLLMENT_TYPE", "UF_CRM_1789736997226")
    monkeypatch.setenv("BITRIX_ENROLLMENT_ONE_ONE_ENUM_IDS", "19704")
    get_settings.cache_clear()
    settings = get_settings()

    rows = [
        {
            "productId": 10,
            "productName": "AWS",
            "price": 6000,
            "quantity": 1,
            "taxRate": 0,
            "taxIncluded": "Y",
        }
    ]
    gate = evaluate_price_gate(rows, {10: Decimal("6000.00")})
    assert gate.ok is True

    forced = apply_enrollment_type_to_gate(
        gate, {"UF_CRM_1789736997226": "19704"}, settings
    )
    assert forced.ok is False
    assert ONE_ON_ONE_APPROVAL_REASON in forced.reason
    assert forced.total_payable == Decimal("6000.00")

    batch = apply_enrollment_type_to_gate(
        gate, {"UF_CRM_1789736997226": "19702"}, settings
    )
    assert batch.ok is True


@pytest.mark.asyncio
async def test_one_one_enrollment_requires_manager_even_when_catalog_ok(
    db_session, monkeypatch
):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "")
    monkeypatch.setenv("BITRIX_FIELD_ENROLLMENT_TYPE", "UF_CRM_1789736997226")
    monkeypatch.setenv("BITRIX_ENROLLMENT_ONE_ONE_ENUM_IDS", "19704")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_user(101, email="owner@test.com", name="Lead Owner", department_ids=[5])
    bitrix.seed_user(
        202, email="manager@test.com", name="Sales Manager", department_ids=[5]
    )
    bitrix.seed_department_manager(5, 202)
    bitrix.seed_lead(
        910, email="oneone@test.com", name="One One Lead", amount=Decimal("6000")
    )
    bitrix._mock_leads[910]["UF_CRM_1789736997226"] = "19704"
    bitrix._mock_leads[910]["ASSIGNED_BY_ID"] = 101
    bitrix.seed_catalog_product(10, name="AWS", price=Decimal("6000"))
    bitrix.seed_lead_products(
        910,
        [
            {
                "productId": 10,
                "productName": "AWS",
                "price": 6000,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as pending:
        await orchestrator.initiate_payment_from_lead(910)

    assert "One-One" in pending.value.args[0]
    approval = orchestrator.approval_service.get_by_token(
        pending.value.approval_url.rsplit("/", 1)[-1]
    )
    assert "enrollment" in (approval.lines_payload or {}).get("approval_kinds", [])
    assert ONE_ON_ONE_APPROVAL_REASON in (approval.reason or "")


@pytest.mark.asyncio
async def test_batch_enrollment_passes_when_catalog_ok(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "true")
    monkeypatch.setenv("BITRIX_FIELD_ENROLLMENT_TYPE", "UF_CRM_1789736997226")
    monkeypatch.setenv("BITRIX_ENROLLMENT_BATCH_ENUM_IDS", "19702")
    get_settings.cache_clear()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(
        911, email="batch@test.com", name="Batch Lead", amount=Decimal("6000")
    )
    bitrix._mock_leads[911]["UF_CRM_1789736997226"] = "19702"
    bitrix.seed_catalog_product(10, name="AWS", price=Decimal("6000"))
    bitrix.seed_lead_products(
        911,
        [
            {
                "productId": 10,
                "productName": "AWS",
                "price": 6000,
                "quantity": 1,
                "taxRate": 0,
                "taxIncluded": "Y",
            }
        ],
    )

    orchestrator = WorkflowOrchestrator(db_session)
    session = await orchestrator.initiate_payment_from_lead(911)
    assert session is not None
    assert session.token
