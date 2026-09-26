"""Bank / cash desk: double-approve must not credit the customer twice."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.models.bank_transfer import STATUS_PENDING_REVIEW, BankTransferSubmission
from app.models.cash_collection import STATUS_CLAIMED, CashCollection
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import ROLE_EMPLOYEE, ROLE_MANAGER, StaffUser
from app.services.bank_transfer_service import BankTransferService
from app.services.cash_collection_service import CashCollectionService
from app.services.workflow_orchestrator import WorkflowOrchestrator


def test_desk_transaction_ids_are_deterministic():
    assert BankTransferService.new_transaction_id(42) == "BT-42"
    assert CashCollectionService.new_cash_transaction_id(7) == "CASH-7"
    assert CashCollectionService.new_pos_transaction_id(7) == "POS-7"
    assert BankTransferService.new_transaction_id(42) == BankTransferService.new_transaction_id(42)


def _txn_count(db, workflow_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(PaymentTransaction.workflow_id == workflow_id)
        )
        or 0
    )


@pytest.mark.asyncio
async def test_bank_transfer_double_approve_credits_once(db_session):
    workflow = CustomerWorkflow(
        bitrix_lead_id=900001,
        customer_name="BT Double",
        customer_email="bt@example.com",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
    )
    manager = StaffUser(
        email="mgr-bt@example.com",
        name="Manager",
        password_hash="x",
        role=ROLE_MANAGER,
        is_active=True,
    )
    db_session.add_all([workflow, manager])
    db_session.flush()

    submission = BankTransferSubmission(
        workflow_id=workflow.id,
        bitrix_lead_id=900001,
        installment_number=1,
        due_amount=Decimal("50.00"),
        currency="AED",
        status=STATUS_PENDING_REVIEW,
        proof_path="proofs/bt-test.jpg",
        proof_original_name="receipt.jpg",
    )
    db_session.add(submission)
    db_session.commit()

    service = BankTransferService(db_session, get_settings())
    await service.approve(submission.id, staff=manager)

    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("50.00")
    assert _txn_count(db_session, workflow.id) == 1
    txn = db_session.scalar(
        select(PaymentTransaction).where(PaymentTransaction.workflow_id == workflow.id)
    )
    assert txn is not None
    assert txn.transaction_id == f"BT-{submission.id}"

    with pytest.raises(ValueError, match="Already approved"):
        await service.approve(submission.id, staff=manager)

    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("50.00")
    assert _txn_count(db_session, workflow.id) == 1


@pytest.mark.asyncio
async def test_cash_double_collect_credits_once(db_session):
    workflow = CustomerWorkflow(
        bitrix_lead_id=900002,
        customer_name="Cash Double",
        customer_email="cash@example.com",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
    )
    employee = StaffUser(
        email="emp-cash@example.com",
        name="Employee",
        password_hash="x",
        role=ROLE_EMPLOYEE,
        is_active=True,
    )
    db_session.add_all([workflow, employee])
    db_session.flush()

    collection = CashCollection(
        workflow_id=workflow.id,
        bitrix_lead_id=900002,
        installment_number=1,
        due_amount=Decimal("40.00"),
        currency="AED",
        status=STATUS_CLAIMED,
        claimed_by_id=employee.id,
        claimed_at=datetime.now(timezone.utc),
        details_ready_at=datetime.now(timezone.utc),
        proof_path="proofs/cash-test.jpg",
        proof_original_name="cash.jpg",
    )
    db_session.add(collection)
    db_session.commit()

    orchestrator = WorkflowOrchestrator(db_session, get_settings())
    await orchestrator.collect_cash(collection.id, staff_id=employee.id)

    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("40.00")
    assert _txn_count(db_session, workflow.id) == 1
    txn = db_session.scalar(
        select(PaymentTransaction).where(PaymentTransaction.workflow_id == workflow.id)
    )
    assert txn is not None
    assert txn.transaction_id == f"CASH-{collection.id}"

    with pytest.raises(ValueError, match="Already collected"):
        await orchestrator.collect_cash(collection.id, staff_id=employee.id)

    db_session.refresh(workflow)
    assert workflow.amount_paid == Decimal("40.00")
    assert _txn_count(db_session, workflow.id) == 1


def test_production_forces_mock_off(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("USE_MOCK_INTEGRATIONS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    settings = Settings()
    assert settings.use_mock_integrations is False
    get_settings.cache_clear()


def test_tamara_and_mock_code_defaults():
    """Code defaults: mocks off, Tamara live (env may override in Settings())."""
    fields = Settings.model_fields
    assert fields["use_mock_integrations"].default is False
    assert fields["tamara_base_url"].default == "https://api.tamara.co"
