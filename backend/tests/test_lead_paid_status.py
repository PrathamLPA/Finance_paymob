"""The lead's Paid Status follows every confirmed payment, not just the first."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.models.customer_workflow import CustomerWorkflow
from app.services.workflow_orchestrator import WorkflowOrchestrator

FIELD = "UF_CRM_1789557091401"


def _settings(**kwargs) -> Settings:
    base = dict(
        use_mock_integrations=True,
        bitrix_field_complete_paid_status=FIELD,
        bitrix_complete_paid_status_fully_paid_enum="19692",
        bitrix_complete_paid_status_partially_paid_enum="19700",
        public_base_url="http://api.test",
        payment_frontend_base_url="http://frontend.test",
    )
    base.update(kwargs)
    return Settings(**base)


def _workflow(db, *, total: str, paid: str) -> CustomerWorkflow:
    workflow = CustomerWorkflow(
        bitrix_lead_id=9301,
        customer_name="Paid Status",
        customer_email="customer@learnerspoint.org",
        total_amount=Decimal(total),
        amount_paid=Decimal(paid),
        currency="AED",
    )
    db.add(workflow)
    db.commit()
    return workflow


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paid,expected",
    [("40.00", "19700"), ("100.00", "19692"), ("120.00", "19692")],
)
async def test_lead_paid_status_follows_the_balance(db_session, paid, expected):
    workflow = _workflow(db_session, total="100.00", paid=paid)
    orch = WorkflowOrchestrator(db_session, _settings())
    orch.bitrix.update_lead_fields = AsyncMock()

    await orch._sync_lead_paid_status(workflow)

    orch.bitrix.update_lead_fields.assert_awaited_once_with(9301, {FIELD: expected})


@pytest.mark.asyncio
async def test_lead_paid_status_untouched_before_any_money(db_session):
    workflow = _workflow(db_session, total="100.00", paid="0.00")
    orch = WorkflowOrchestrator(db_session, _settings())
    orch.bitrix.update_lead_fields = AsyncMock()

    await orch._sync_lead_paid_status(workflow)

    orch.bitrix.update_lead_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_lead_paid_status_failure_does_not_break_the_payment(db_session):
    workflow = _workflow(db_session, total="100.00", paid="50.00")
    orch = WorkflowOrchestrator(db_session, _settings())
    orch.bitrix.update_lead_fields = AsyncMock(side_effect=RuntimeError("bitrix down"))

    await orch._sync_lead_paid_status(workflow)  # must not raise
