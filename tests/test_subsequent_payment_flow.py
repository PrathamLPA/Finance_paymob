"""Tests for subsequent payment workflow."""

from decimal import Decimal

from sqlalchemy import select

from app.models.customer_workflow import CustomerWorkflow


def _complete_first_payment(client, seed_lead, lead_id: int = 301) -> dict:
    seed_lead(lead_id, email="subsequent@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": lead_id, "customer_email": "subsequent@test.com", "total_amount": "10000"},
    ).json()
    client.post(f"/payment/{link['token']}/accept", data={"accepted": "yes"}, follow_redirects=False)
    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": link["merchant_reference"], "amount": "4000"},
    ).json()
    return payment


def test_second_payment_updates_same_invoice(client, seed_lead, db_session):
    first = _complete_first_payment(client, seed_lead, lead_id=301)
    invoice_id = first["zoho_invoice_id"]
    finance_deal_id = first["finance_deal_id"]

    link = client.post(
        "/api/dev/send-payment-link",
        json={"finance_deal_id": finance_deal_id},
    )
    assert link.status_code == 200
    new_token = link.json()["token"]
    new_ref = link.json()["merchant_reference"]

    client.post(f"/payment/{new_token}/accept", data={"accepted": "yes"}, follow_redirects=False)

    second = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": new_ref, "amount": "2000"},
    ).json()

    assert second["status"] == "ok"
    assert second["zoho_invoice_id"] == invoice_id
    assert second["amount_paid"] == "6000.00"
    assert second["remaining_balance"] == "4000.00"

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 301))
    assert workflow.zoho_invoice_id == invoice_id
    assert len(workflow.transactions) == 2


def test_finance_deal_trigger_creates_new_session(client, seed_lead):
    first = _complete_first_payment(client, seed_lead, lead_id=302)
    finance_deal_id = first["finance_deal_id"]

    webhook = client.post(
        "/webhooks/bitrix24",
        json={
            "event": "ONCRMDEALUPDATE",
            "data": {"FIELDS": {"ID": finance_deal_id, "STAGE_ID": "FINANCE_GENERATE_LINK"}},
        },
    )
    assert webhook.status_code == 200
    assert webhook.json()["status"] == "processed"
    assert "payment_url" in webhook.json()
