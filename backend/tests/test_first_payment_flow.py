"""Tests for first payment workflow."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.integrations.factory import get_email_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_transaction import PaymentTransaction
from tests.conftest import SAMPLE_REGISTRANT


def test_lead_trigger_email_uses_middleware_url_not_paymob(client, seed_lead):
    seed_lead(201, email="pay@test.com")
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 201, "customer_email": "pay@test.com", "total_amount": "10000"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["payment_url"].startswith("http://frontend.test/payment/")
    assert "mock.paymob" not in data["payment_url"]

    email_client = get_email_client()
    assert len(email_client.sent_emails) >= 1
    body = email_client.sent_emails[-1]["body"]
    assert "http://frontend.test/payment/" in body
    assert "mock.paymob" not in body


def test_first_payment_creates_three_deals_and_invoice(client, seed_lead, db_session):
    seed_lead(202, email="first@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 202, "customer_email": "first@test.com", "total_amount": "10000"},
    )
    token = link.json()["token"]

    client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    # Accept refreshes Paymob checkout and rotates merchant_reference.
    from app.models.payment_session import PaymentSession

    session = db_session.scalar(select(PaymentSession).where(PaymentSession.token == token))
    assert session is not None
    merchant_reference = session.merchant_reference
    db_session.expire_all()

    lookup = client.get(f"/api/payment/lookup/{merchant_reference}")
    assert lookup.status_code == 200
    assert lookup.json()["course_for"] == "self"
    assert lookup.json()["show_lms"] is True
    assert "learn.learnerspoint.org" in (lookup.json()["lms_url"] or "")

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

    from app.integrations.factory import get_bitrix_client

    bitrix = get_bitrix_client()
    lead_comments = bitrix._mock_comments.get(("LEAD", 202), [])
    assert any("Zoho invoice" in item["COMMENT"] for item in lead_comments)
    if workflow.finance_deal_id:
        deal_comments = bitrix._mock_comments.get(("DEAL", workflow.finance_deal_id), [])
        assert any("Zoho invoice" in item["COMMENT"] for item in deal_comments)
    if workflow.bitrix_estimate_id:
        estimate_comments = bitrix._mock_comments.get(("QUOTE", workflow.bitrix_estimate_id), [])
        assert any("Zoho invoice" in item["COMMENT"] for item in estimate_comments)
        assert any(
            "Invoice_" in name
            for item in estimate_comments
            for name in (item.get("FILES") or [])
        )


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


def test_first_payment_uses_sales_pipeline_and_notifies_agent(client, seed_lead, db_session):
    seed_lead(204, email="sales@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 204, "customer_email": "sales@test.com", "total_amount": "10000"},
    )
    token = link.json()["token"]
    client.post(f"/api/payment/{token}/accept", json={"accepted": True, **SAMPLE_REGISTRANT})

    from app.models.payment_session import PaymentSession

    session = db_session.scalar(select(PaymentSession).where(PaymentSession.token == token))
    assert session is not None
    merchant_reference = session.merchant_reference
    db_session.expire_all()

    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": merchant_reference, "amount": "3000"},
    )
    assert payment.status_code == 200

    from app.integrations.factory import get_bitrix_client, get_email_client

    bitrix = get_bitrix_client()
    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 204))
    assert workflow is not None
    deal = bitrix._mock_deals[workflow.sales_deal_id]
    assert str(deal["CATEGORY_ID"]) == "16"
    lead = bitrix._mock_leads[204]
    assert lead["STATUS_ID"] == "CONVERTED"

    comments = bitrix._mock_comments[("LEAD", 204)]
    assert any("Payment successful" in item["COMMENT"] for item in comments)
    assert any("Payment successful" in note["message"] for note in bitrix._mock_notifications)
    emails = get_email_client().sent_emails
    assert any("successful" in email["subject"].lower() and email["to"] == "agent@test.com" for email in emails)


@pytest.mark.asyncio
async def test_failed_payment_comments_and_emails_agent_without_converting(
    client, seed_lead, db_session
):
    seed_lead(205, email="fail@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 205, "customer_email": "fail@test.com", "total_amount": "10000"},
    )
    merchant_reference = link.json()["merchant_reference"]

    from app.integrations.factory import get_bitrix_client, get_email_client
    from app.integrations.paymob import build_mock_paymob_payload
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    payload = build_mock_paymob_payload(
        transaction_id=555001,
        amount_cents=300000,
        currency="AED",
        merchant_order_id=merchant_reference,
        order_id=777,
        success=False,
    )
    orchestrator = WorkflowOrchestrator(db_session)
    workflow = await orchestrator.handle_paymob_payload(payload)

    assert workflow is not None
    assert workflow.amount_paid == Decimal("0.00")
    assert workflow.sales_deal_id is None
    assert all(not txn.success for txn in workflow.transactions)

    bitrix = get_bitrix_client()
    comments = bitrix._mock_comments[("LEAD", 205)]
    assert any("Payment failed" in item["COMMENT"] for item in comments)
    assert any("Payment failed" in note["message"] for note in bitrix._mock_notifications)
    emails = get_email_client().sent_emails
    assert any("failed" in email["subject"].lower() and email["to"] == "agent@test.com" for email in emails)
