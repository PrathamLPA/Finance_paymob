"""Installment policy → manager approval tests."""

from decimal import Decimal

import pytest

from app.config import get_settings
from app.integrations.factory import get_bitrix_client, get_email_client
from app.services.installment_plan import evaluate_installment_policy
from app.services.price_approval_service import PriceApprovalPending
from app.services.workflow_orchestrator import WorkflowOrchestrator
from tests.test_installment_plan import _settings


def test_policy_first_installment_below_50_percent():
    settings = _settings()
    result = evaluate_installment_policy(
        {"UF_I1": "1000"},
        settings,
        payable_total=Decimal("3000.00"),
        required_percent=50,
    )
    assert result.needs_approval is True
    assert any("below the 50" in r for r in result.reasons)


def test_policy_count_more_than_two():
    settings = _settings()
    lead = {
        "UF_COUNT": "3",
        "UF_I1": "1500",
        "UF_D1": "2026-01-01",
        "UF_I2": "750",
        "UF_D2": "2026-01-15",
        "UF_I3": "750",
        "UF_D3": "2026-01-30",
    }
    result = evaluate_installment_policy(
        lead, settings, payable_total=Decimal("3000.00"), required_percent=50
    )
    assert result.needs_approval is True
    assert result.count_above_two is True
    assert any("more than 2" in r for r in result.reasons)


def test_garbage_installment_count_is_ignored():
    settings = _settings()
    lead = {
        "UF_COUNT": "5830",
        "UF_I1": "1500",
        "UF_D1": "2026-01-01",
        "UF_I2": "1500",
        "UF_D2": "2026-01-20",
    }
    result = evaluate_installment_policy(
        lead, settings, payable_total=Decimal("3000.00"), required_percent=50
    )
    assert result.installment_count == 2
    assert result.count_above_two is False
    assert result.needs_approval is False


def test_missing_amount_flagged_for_manager():
    settings = _settings()
    lead = {
        "UF_COUNT": "2",
        "UF_I1": "1500",
        "UF_D1": "2026-01-01",
        "UF_D2": "2026-01-20",
    }
    result = evaluate_installment_policy(
        lead, settings, payable_total=Decimal("3000.00"), required_percent=50
    )
    assert result.missing_amounts is True
    assert result.needs_approval is True


def test_policy_gap_over_one_month():
    settings = _settings()
    lead = {
        "UF_COUNT": "2",
        "UF_I1": "1500",
        "UF_D1": "2026-01-01",
        "UF_I2": "1500",
        "UF_D2": "2026-03-15",
    }
    result = evaluate_installment_policy(
        lead, settings, payable_total=Decimal("3000.00"), required_percent=50
    )
    assert result.needs_approval is True
    assert any("days after Installment 1" in r for r in result.reasons)


def test_policy_ok_when_rules_pass():
    settings = _settings()
    lead = {
        "UF_COUNT": "2",
        "UF_I1": "1500",
        "UF_D1": "2026-01-01",
        "UF_I2": "1500",
        "UF_D2": "2026-01-20",
    }
    result = evaluate_installment_policy(
        lead, settings, payable_total=Decimal("3000.00"), required_percent=50
    )
    assert result.needs_approval is False


@pytest.mark.asyncio
async def test_installment_policy_requests_manager_approval(db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "false")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "manager@test.com")
    settings = _settings()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(720, email="policy@test.com", name="Policy", amount=Decimal("3000"))
    bitrix._mock_leads[720].update(
        {
            "ASSIGNED_BY_ID": 101,
            settings.bitrix_field_installment_count: "3",
            settings.bitrix_field_installment_1: "1500",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "750",
            settings.bitrix_field_installment_2_due_date: "2026-01-15",
            settings.bitrix_field_installment_3: "750",
            settings.bitrix_field_installment_3_due_date: "2026-01-30",
        }
    )
    bitrix.seed_user(101, email="owner@test.com", name="Owner", department_ids=[5])
    bitrix.seed_user(202, email="manager@test.com", name="Manager", department_ids=[5])
    bitrix.seed_department_manager(5, 202)

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as pending:
        await orchestrator.initiate_payment_from_lead(720)

    approval = orchestrator.approval_service.get_by_token(
        pending.value.approval_url.rsplit("/", 1)[-1]
    )
    assert approval is not None
    public = orchestrator.approval_service.to_public_dict(approval)
    assert "installment" in public["approval_kinds"]
    assert public["installment_policy"]["needs_approval"] is True
    assert any("more than 2" in r for r in public["installment_policy"]["reasons"])

    emails = get_email_client().sent_emails
    assert emails
    assert "Approval needed" in emails[-1]["subject"]
    assert "Installment policy" in emails[-1]["body"]

    session = await orchestrator.complete_approved_payment(approval.token, note="OK plan")
    assert session.charge_amount == Decimal("1500.00")
    assert session.charge_source == "installment_1"


@pytest.mark.asyncio
async def test_first_installment_below_50_needs_approval_even_without_full_plan(
    db_session, monkeypatch
):
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "false")
    monkeypatch.setenv("BITRIX_APPROVAL_FALLBACK_EMAIL", "manager@test.com")
    settings = _settings()

    bitrix = get_bitrix_client()
    bitrix.seed_lead(721, email="low@test.com", name="Low First", amount=Decimal("4000"))
    bitrix._mock_leads[721].update(
        {
            settings.bitrix_field_installment_1: "1000",
        }
    )

    orchestrator = WorkflowOrchestrator(db_session)
    with pytest.raises(PriceApprovalPending) as pending:
        await orchestrator.initiate_payment_from_lead(721)

    approval = orchestrator.approval_service.get_by_token(
        pending.value.approval_url.rsplit("/", 1)[-1]
    )
    public = orchestrator.approval_service.to_public_dict(approval)
    assert "installment" in public["approval_kinds"]
    assert any("below the 50" in r for r in public["installment_policy"]["reasons"])
