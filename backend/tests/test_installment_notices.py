"""Tests for installment due-date client emails."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.integrations.bitrix import parse_lead_customer_details
from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import CustomerWorkflow
from app.services.installment_notices import is_installment_plan, next_due_installment, parse_bitrix_date
from tests.conftest import SAMPLE_REGISTRANT


def test_parse_lead_prefers_client_email_field():
    settings = get_settings()
    lead = {
        "NAME": "Aisha",
        "LAST_NAME": "Khan",
        "EMAIL": [{"VALUE": "crm-email@test.com", "VALUE_TYPE": "WORK"}],
        settings.bitrix_field_client_email: "client-from-uf@test.com",
    }
    email, name = parse_lead_customer_details(
        lead,
        client_email_field=settings.bitrix_field_client_email,
        fallback_email_field=settings.bitrix_field_customer_email,
    )
    assert email == "client-from-uf@test.com"
    assert name == "Aisha Khan"


def test_next_due_installment_skips_paid_slot():
    settings = get_settings()
    today = date(2026, 8, 24)
    lead = {
        settings.bitrix_field_installment_count: 3,
        settings.bitrix_field_installment_1: "500",
        settings.bitrix_field_installment_1_date: "2026-08-01",
        settings.bitrix_field_installment_2: "500",
        settings.bitrix_field_installment_2_due_date: "2026-08-24",
        settings.bitrix_field_installment_3: "500",
        settings.bitrix_field_installment_3_due_date: "2026-09-24",
    }
    assert is_installment_plan(lead, settings) is True
    slot = next_due_installment(lead, settings, amount_paid=Decimal("500"), today=today)
    assert slot is not None
    assert slot.number == 2
    assert slot.due_date == today


def test_parse_bitrix_date_formats():
    assert parse_bitrix_date("24/08/2026") == date(2026, 8, 24)
    assert parse_bitrix_date("2026-08-24T00:00:00+04:00") == date(2026, 8, 24)


def test_installment_due_date_emails_client_from_uf_field(client, seed_lead, db_session):
    settings = get_settings()
    seed_lead(306, email="crm-email@test.com", amount=Decimal("1500"))
    bitrix = get_bitrix_client()
    today = date.today().isoformat()
    bitrix._mock_leads[306].update(
        {
            settings.bitrix_field_client_email: "installment-client@test.com",
            settings.bitrix_field_installment_count: 3,
            settings.bitrix_field_installment_1: "500",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "500",
            settings.bitrix_field_installment_2_due_date: today,
            settings.bitrix_field_installment_3: "500",
            settings.bitrix_field_installment_3_due_date: "2026-12-01",
        }
    )

    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 306, "customer_email": "crm-email@test.com", "total_amount": "1500"},
    )
    token = link.json()["token"]
    client.post(f"/api/payment/{token}/accept", json={"accepted": True, **SAMPLE_REGISTRANT})
    from app.models.payment_session import PaymentSession

    session = db_session.scalar(select(PaymentSession).where(PaymentSession.token == token))
    assert session is not None
    merchant_reference = session.merchant_reference
    db_session.expire_all()
    paid = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": merchant_reference, "amount": "500"},
    )
    assert paid.status_code == 200

    bitrix._mock_leads[306].update(
        {
            settings.bitrix_field_client_email: "installment-client@test.com",
            settings.bitrix_field_installment_count: 3,
            settings.bitrix_field_installment_1: "500",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "500",
            settings.bitrix_field_installment_2_due_date: today,
        }
    )

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 306))
    assert workflow is not None
    workflow.last_reminder_at = datetime.now(timezone.utc)
    db_session.commit()

    email_client = get_email_client()
    before = len(email_client.sent_emails)
    result = client.post("/api/dev/process-reminders")
    assert result.status_code == 200
    assert result.json()["sent"] >= 1
    assert len(email_client.sent_emails) > before
    latest = email_client.sent_emails[-1]
    assert latest["to"] == "installment-client@test.com"
    assert "Installment 2" in latest["subject"]

    db_session.refresh(workflow)
    assert workflow.installment_notices_sent.get("2")

    again = client.post("/api/dev/process-reminders")
    assert again.json()["sent"] == 0
