"""Tests for first payment workflow."""

from decimal import Decimal

from sqlalchemy import select

from app.integrations.factory import get_email_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_transaction import PaymentTransaction


def test_lead_trigger_email_uses_middleware_url_not_paymob(client, seed_lead):
    seed_lead(201, email="pay@test.com")
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 201, "customer_email": "pay@test.com", "total_amount": "10000"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["payment_url"].startswith("http://testserver/payment/")
    assert "mock.paymob" not in data["payment_url"]

    email_client = get_email_client()
    assert len(email_client.sent_emails) >= 1
    body = email_client.sent_emails[-1]["body"]
    assert "http://testserver/payment/" in body
    assert "mock.paymob" not in body


def test_first_payment_creates_three_deals_and_invoice(client, seed_lead, db_session):
    seed_lead(202, email="first@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 202, "customer_email": "first@test.com", "total_amount": "10000"},
    )
    token = link.json()["token"]
    merchant_reference = link.json()["merchant_reference"]

    client.post(f"/payment/{token}/accept", data={"accepted": "yes"}, follow_redirects=False)

    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": merchant_reference, "amount": "3000"},
    )
    assert payment.status_code == 200
    data = payment.json()
    assert data["status"] == "ok"
    assert data["sales_deal_id"] is not None
    assert data["finance_deal_id"] is not None
    assert data["b2c_deal_id"] is not None
    assert data["zoho_invoice_id"] == "MOCK-INV-1"
    assert data["amount_paid"] == "3000.00"
    assert data["remaining_balance"] == "7000.00"

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 202))
    assert workflow is not None
    assert workflow.first_payment_at is not None
    assert len(workflow.transactions) == 1


def test_duplicate_transaction_is_ignored(client, seed_lead):
    seed_lead(203, email="dup@test.com")
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 203, "customer_email": "dup@test.com"},
    )
    merchant_reference = link.json()["merchant_reference"]

    first = client.post("/api/dev/simulate-paymob-webhook", json={"merchant_reference": merchant_reference})
    second = client.post("/api/dev/simulate-paymob-webhook", json={"merchant_reference": merchant_reference})

    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "duplicate"
