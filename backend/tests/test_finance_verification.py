"""Finance-manager verification holds side effects only while the switch is on."""

from decimal import Decimal

from app.config import Settings
from app.models.customer_workflow import CustomerWorkflow
from app.models.finance_verification import STATUS_PENDING, FinanceVerification
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import ROLE_ADMIN, StaffUser
from app.services.finance_verification_service import FinanceVerificationService
from app.services.staff_auth import hash_password


def _settings(**kwargs) -> Settings:
    base = dict(
        database_url="sqlite://",
        use_mock_integrations=True,
        finance_manager_verification=False,
    )
    base.update(kwargs)
    return Settings(**base)


def _workflow(db) -> CustomerWorkflow:
    row = CustomerWorkflow(
        bitrix_lead_id=595001,
        customer_name="Ada",
        total_amount=Decimal("10.00"),
        amount_paid=Decimal("10.00"),
        currency="AED",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _txn(db, workflow: CustomerWorkflow) -> PaymentTransaction:
    row = PaymentTransaction(
        workflow_id=workflow.id,
        transaction_id="PAY-1",
        amount=Decimal("10.00"),
        currency="AED",
        remaining_balance=Decimal("0.00"),
        source_type="online",
        success=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_switch_off_does_not_hold(db_session):
    workflow = _workflow(db_session)
    txn = _txn(db_session, workflow)
    service = FinanceVerificationService(db_session, _settings())
    held = service.hold_if_required(
        workflow,
        txn,
        amount=Decimal("10.00"),
        currency="AED",
        comment_prefix="Payment successful",
        skip_zoho=False,
        skip_deals=False,
        finance_release=False,
        dev_simulate=False,
    )
    assert held is False
    assert db_session.query(FinanceVerification).count() == 0


def test_switch_on_queues_and_admin_can_turn_it_off(db_session):
    workflow = _workflow(db_session)
    txn = _txn(db_session, workflow)
    admin = StaffUser(
        email="admin@example.com",
        name="Admin",
        password_hash=hash_password("secret1"),
        role=ROLE_ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    service = FinanceVerificationService(
        db_session, _settings(finance_manager_verification=True)
    )
    assert service.is_enabled() is True
    held = service.hold_if_required(
        workflow,
        txn,
        amount=Decimal("10.00"),
        currency="AED",
        comment_prefix="Payment successful",
        skip_zoho=False,
        skip_deals=False,
        finance_release=False,
        dev_simulate=False,
    )
    assert held is True
    queued = db_session.query(FinanceVerification).one()
    assert queued.status == STATUS_PENDING
    # A second pass does not create another row.
    assert (
        service.hold_if_required(
            workflow,
            txn,
            amount=Decimal("10.00"),
            currency="AED",
            comment_prefix="Payment successful",
            skip_zoho=False,
            skip_deals=False,
            finance_release=False,
            dev_simulate=False,
        )
        is True
    )
    assert db_session.query(FinanceVerification).count() == 1
    service.set_enabled(False, admin)
    assert service.is_enabled() is False
