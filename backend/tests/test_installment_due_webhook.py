"""Bitrix BP Outbound webhook → installment due payment link + email."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import CustomerWorkflow
from app.services.installment_notices import next_due_installment
from tests.conftest import SAMPLE_REGISTRANT
from tests.test_bitrix_webhook import _finance_deal


def test_next_due_installment_early_days():
    settings = get_settings()
    today = date(2026, 8, 23)
    lead = {
        settings.bitrix_field_installment_count: 2,
        settings.bitrix_field_installment_1: "500",
        settings.bitrix_field_installment_1_date: "2026-08-01",
        settings.bitrix_field_installment_2: "500",
        settings.bitrix_field_installment_2_due_date: "2026-08-24",
    }
    assert next_due_installment(lead, settings, amount_paid=Decimal("500"), today=today) is None
    slot = next_due_installment(
        lead, settings, amount_paid=Decimal("500"), today=today, early_days=1
    )
    assert slot is not None
    assert slot.number == 2


def test_installment_due_webhook_creates_link_and_emails(client, seed_lead, db_session):
    settings = get_settings()
    deal_id = _finance_deal(client, seed_lead, db_session, 501)
    bitrix = get_bitrix_client()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.finance_deal_id == deal_id)
    )
    assert workflow is not None
    lead_id = workflow.bitrix_lead_id
    bitrix._mock_leads[lead_id].update(
        {
            settings.bitrix_field_client_email: "i2-due@test.com",
            settings.bitrix_field_installment_count: 3,
            settings.bitrix_field_installment_1: "1000",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "1000",
            settings.bitrix_field_installment_2_due_date: tomorrow,
            settings.bitrix_field_installment_3: "8000",
            settings.bitrix_field_installment_3_due_date: "2026-12-01",
        }
    )
    workflow.bitrix_lead_payload = dict(bitrix._mock_leads[lead_id])
    workflow.installment_notices_sent = None
    db_session.commit()

    email_client = get_email_client()
    before = len(email_client.sent_emails)

    response = client.post(
        f"/webhooks/bitrix24/installment-due?deal_id={deal_id}&installment=2",
        data={
            "document_id[0]": "crm",
            "document_id[1]": "CCrmDocumentDeal",
            "document_id[2]": f"DEAL_{deal_id}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["installment_number"] == 2
    assert body["payment_url"]
    assert len(email_client.sent_emails) > before
    assert "Installment 2" in email_client.sent_emails[-1]["subject"]

    db_session.refresh(workflow)
    assert workflow.installment_notices_sent.get("2")

    second = client.post(
        f"/webhooks/bitrix24/installment-due?deal_id={deal_id}&installment=2"
    ).json()
    assert second["status"] == "ignored"
    assert second["reason"] == "notice_already_sent"


def test_installment_due_webhook_query_token_auth(client, seed_lead, db_session, monkeypatch):
    deal_id = _finance_deal(client, seed_lead, db_session, 502)
    monkeypatch.setenv("BITRIX_WEBHOOK_SECRET", "bp-secret")
    get_settings.cache_clear()

    rejected = client.post(
        f"/webhooks/bitrix24/installment-due?deal_id={deal_id}&installment=2&token=wrong"
    )
    assert rejected.status_code == 401

    # May ignore for business reasons after auth; must not 401.
    accepted = client.post(
        f"/webhooks/bitrix24/installment-due?deal_id={deal_id}&installment=2&token=bp-secret"
    )
    assert accepted.status_code == 200
    get_settings.cache_clear()
