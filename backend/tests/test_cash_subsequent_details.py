"""Subsequent cash installments inherit form-fill from first payment."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.models.cash_collection import CashCollection
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import (
    CHANNEL_CASH,
    SESSION_COMPLETED,
    SESSION_PENDING,
    SOURCE_LEAD,
    PaymentSession,
)
from app.models.terms_acceptance import TermsAcceptance
from app.services.cash_collection_service import CashCollectionService


def test_subsequent_cash_inherits_details_ready(db_session):
    workflow = CustomerWorkflow(
        bitrix_lead_id=594016,
        customer_name="Sabith",
        customer_email="sabith.learnerspoint@gmail.com",
        customer_phone="324234",
        total_amount=Decimal("4.20"),
        amount_paid=Decimal("2.10"),
        currency="AED",
    )
    db_session.add(workflow)
    db_session.flush()

    expires = datetime.now(timezone.utc) + timedelta(days=1)
    first = PaymentSession(
        workflow_id=workflow.id,
        token="cash-i1-token",
        source_type=SOURCE_LEAD,
        source_id=594016,
        charge_amount=Decimal("2.10"),
        charge_source="installment_1",
        amount_locked=True,
        installment_number=1,
        currency="AED",
        merchant_reference="WF-CASH-I1",
        status=SESSION_COMPLETED,
        channel=CHANNEL_CASH,
        expires_at=expires,
    )
    db_session.add(first)
    db_session.flush()
    db_session.add(
        TermsAcceptance(
            payment_session_id=first.id,
            terms_version="1.0",
            course_for="self",
            registrant_name="Sabith Gmail",
            registrant_email="sabith.learnerspoint@gmail.com",
            registrant_phone="324234",
        )
    )
    db_session.commit()

    cash = CashCollectionService(db_session, get_settings())
    row = cash.enqueue_from_workflow(
        workflow,
        due_amount=Decimal("2.10"),
        installment_number=2,
    )

    assert row.installment_number == 2
    assert row.details_ready_at is not None
    assert cash._collection_details_ready(row) is True
    assert row.customer_name == "Sabith Gmail"
    assert row.customer_email == "sabith.learnerspoint@gmail.com"


def test_first_cash_still_requires_form_fill(db_session):
    workflow = CustomerWorkflow(
        bitrix_lead_id=594017,
        customer_name="New Lead",
        customer_email="new@test.com",
        customer_phone="100",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
    )
    db_session.add(workflow)
    db_session.commit()

    cash = CashCollectionService(db_session, get_settings())
    row = cash.enqueue_from_workflow(
        workflow,
        due_amount=Decimal("50.00"),
        installment_number=1,
    )

    assert row.details_ready_at is None
    assert cash._collection_details_ready(row) is False
