"""Seed mock customer workflows and Paymob-shaped transaction data."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.paymob import build_mock_paymob_payload
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import SESSION_PENDING, PaymentSession
from app.models.payment_transaction import PaymentTransaction
from app.services.paymob_mapper import apply_paymob_fields
from app.services.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)

MOCK_CUSTOMERS = [
    {
        "lead_id": 2001,
        "name": "Ahmed Al Rashid",
        "email": "ahmed.rashid@example.com",
        "phone": "+971501234567",
        "total": Decimal("15000.00"),
        "paid": Decimal("5000.00"),
        "with_payment": True,
    },
    {
        "lead_id": 2002,
        "name": "Sarah Johnson",
        "email": "sarah.j@example.com",
        "phone": "+971509876543",
        "total": Decimal("8500.00"),
        "paid": Decimal("0.00"),
        "with_payment": False,
    },
    {
        "lead_id": 2003,
        "name": "Mohammed Hassan",
        "email": "m.hassan@example.com",
        "phone": "+971551112233",
        "total": Decimal("22000.00"),
        "paid": Decimal("11000.00"),
        "with_payment": True,
    },
]


def seed_mock_data(db: Session) -> dict:
    """Insert or refresh mock customers with Paymob-compatible transaction records."""
    orchestrator = WorkflowOrchestrator(db)
    created = []

    for customer in MOCK_CUSTOMERS:
        existing = db.scalar(
            select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == customer["lead_id"])
        )
        if existing:
            workflow = existing
            workflow.customer_name = customer["name"]
            workflow.customer_email = customer["email"]
            workflow.customer_phone = customer["phone"]
            workflow.total_amount = customer["total"]
        else:
            workflow = CustomerWorkflow(
                bitrix_lead_id=customer["lead_id"],
                customer_name=customer["name"],
                customer_email=customer["email"],
                customer_phone=customer["phone"],
                total_amount=customer["total"],
                currency="AED",
            )
            db.add(workflow)
            db.flush()

        if customer["with_payment"] and customer["paid"] > 0:
            workflow.amount_paid = customer["paid"]
            workflow.first_payment_at = datetime.now(timezone.utc) - timedelta(days=2)
            workflow.sales_deal_id = 900001 + customer["lead_id"]
            workflow.finance_deal_id = 900002 + customer["lead_id"]
            workflow.b2c_deal_id = 900003 + customer["lead_id"]
            workflow.zoho_invoice_id = f"MOCK-INV-{workflow.id}"

            txn_id = f"PM-{customer['lead_id']}-001"
            if not db.scalar(select(PaymentTransaction).where(PaymentTransaction.transaction_id == txn_id)):
                amount_cents = int(customer["paid"] * 100)
                payload = build_mock_paymob_payload(
                    transaction_id=int(customer["lead_id"]) * 1000,
                    amount_cents=amount_cents,
                    currency="AED",
                    merchant_order_id=f"WF-{workflow.id}-seed",
                    order_id=int(customer["lead_id"]) * 2000,
                    email=customer["email"],
                )
                from app.integrations.paymob import MockPaymobClient

                paymob = MockPaymobClient()
                data = paymob.parse_successful_payment(payload)
                if data:
                    txn = PaymentTransaction(
                        workflow_id=workflow.id,
                        transaction_id=txn_id,
                        order_id=str(data.paymob_order_id),
                        amount=customer["paid"],
                        currency="AED",
                        remaining_balance=workflow.remaining_balance,
                        raw_payload=data.raw_payload,
                        status="success",
                    )
                    apply_paymob_fields(txn, data)
                    db.add(txn)
        else:
            workflow.amount_paid = Decimal("0.00")
            workflow.first_payment_at = None

        token = secrets.token_urlsafe(32)
        session = PaymentSession(
            workflow_id=workflow.id,
            token=token,
            source_type="lead",
            source_id=customer["lead_id"],
            charge_amount=workflow.remaining_balance or customer["total"],
            currency="AED",
            paymob_session_id=uuid.uuid4().hex[:16],
            paymob_checkout_url=f"https://accept.paymob.com/unifiedcheckout/?publicKey=mock&clientSecret=mock_{token[:8]}",
            merchant_reference=f"WF-{workflow.id}-{uuid.uuid4().hex[:6]}",
            status=SESSION_PENDING,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
        )
        db.add(session)
        db.flush()

        created.append({
            "lead_id": customer["lead_id"],
            "name": customer["name"],
            "email": customer["email"],
            "payment_url": orchestrator.session_service.build_payment_url(token),
            "amount_paid": str(workflow.amount_paid),
            "remaining": str(workflow.remaining_balance),
        })

    db.commit()
    logger.info("Seeded %s mock customers", len(created))
    return {"customers": created, "count": len(created)}
