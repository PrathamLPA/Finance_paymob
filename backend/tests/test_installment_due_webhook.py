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
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 501)
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
            # I1 was cash; I2 mode blank — installment-due must still issue Paymob link.
            settings.bitrix_field_payment_1_mode: "5774",
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


def test_installment_due_still_sends_when_threshold_percent_met(client, seed_lead, db_session):
    """50% threshold met must not block Installment 2+ due links."""
    settings = get_settings()
    deal_id = _finance_deal(client, seed_lead, db_session, 503)
    bitrix = get_bitrix_client()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 503)
    )
    assert workflow is not None
    lead_id = workflow.bitrix_lead_id
    bitrix._mock_leads[lead_id].update(
        {
            settings.bitrix_field_client_email: "threshold@test.com",
            settings.bitrix_field_installment_count: 2,
            settings.bitrix_field_installment_1: "5000",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "5000",
            settings.bitrix_field_installment_2_due_date: tomorrow,
        }
    )
    workflow.bitrix_lead_payload = dict(bitrix._mock_leads[lead_id])
    workflow.total_amount = Decimal("10000")
    workflow.amount_paid = Decimal("5000")  # exactly 50% threshold
    workflow.installment_notices_sent = None
    db_session.commit()

    email_client = get_email_client()
    before = len(email_client.sent_emails)
    body = client.post(
        f"/webhooks/bitrix24/installment-due?deal_id={deal_id}&installment=2"
    ).json()
    assert body["status"] == "processed"
    assert body["installment_number"] == 2
    assert body.get("payment_url")
    assert len(email_client.sent_emails) > before


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


def test_installment_due_resolves_via_original_deal_id(client, seed_lead, db_session):
    """Finance UF Original Deal ID → Sales → LEAD_ID (preferred over Contact)."""
    settings = get_settings()
    lead_id = 593071
    seed_lead(lead_id, email="origdeal@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": lead_id,
            "customer_email": "origdeal@test.com",
            "total_amount": "10000",
        },
    ).json()
    client.post(
        f"/api/payment/{link['token']}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    from app.models.payment_session import PaymentSession

    session = db_session.scalar(
        select(PaymentSession).where(PaymentSession.token == link["token"])
    )
    assert session is not None
    assert (
        client.post(
            "/api/dev/simulate-paymob-webhook",
            json={"merchant_reference": session.merchant_reference, "amount": "1000"},
        ).json()["status"]
        == "ok"
    )

    bitrix = get_bitrix_client()
    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == lead_id)
    )
    assert workflow is not None
    workflow.finance_deal_id = None
    workflow.sales_deal_id = None
    bitrix._mock_leads[lead_id].update(
        {
            settings.bitrix_field_client_email: "origdeal@test.com",
            settings.bitrix_field_installment_count: 2,
            settings.bitrix_field_installment_1: "1000",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "9000",
            settings.bitrix_field_installment_2_due_date: (
                date.today() + timedelta(days=1)
            ).isoformat(),
        }
    )
    workflow.bitrix_lead_payload = dict(bitrix._mock_leads[lead_id])
    workflow.installment_notices_sent = None

    sales_id = 152410
    finance_id = 152416
    orig_field = settings.bitrix_field_original_deal_id
    bitrix._mock_deals[sales_id] = {
        "ID": sales_id,
        "LEAD_ID": lead_id,
        "TITLE": "Sales",
        "CATEGORY_ID": settings.bitrix_sales_pipeline_id or "16",
    }
    # No CONTACT_ID / LEAD_ID on Finance — only Original Deal ID.
    bitrix._mock_deals[finance_id] = {
        "ID": finance_id,
        "LEAD_ID": None,
        "TITLE": "Finance",
        "CATEGORY_ID": "44",
        orig_field: str(sales_id),
        "STAGE_ID": settings.bitrix_finance_generate_link_stage_id,
    }
    db_session.commit()

    response = client.post(
        "/webhooks/bitrix24/installment-due?installment=2",
        data={
            "document_id[0]": "crm",
            "document_id[1]": "CCrmDocumentDeal",
            "document_id[2]": f"DEAL_{finance_id}",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    db_session.refresh(workflow)
    assert workflow.finance_deal_id == finance_id
    assert workflow.sales_deal_id == sales_id


def test_installment_due_resolves_orphan_finance_deal_via_contact(client, seed_lead, db_session):
    """Finance tunnel often drops LEAD_ID; recover via Sales sibling + Contact."""
    settings = get_settings()
    lead_id = 593070
    seed_lead(lead_id, email="orphan@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": lead_id,
            "customer_email": "orphan@test.com",
            "total_amount": "10000",
        },
    ).json()
    client.post(
        f"/api/payment/{link['token']}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    from app.models.payment_session import PaymentSession

    session = db_session.scalar(
        select(PaymentSession).where(PaymentSession.token == link["token"])
    )
    assert session is not None
    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": session.merchant_reference, "amount": "1000"},
    ).json()
    assert payment["status"] == "ok"

    bitrix = get_bitrix_client()
    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == lead_id)
    )
    assert workflow is not None
    workflow.finance_deal_id = None
    workflow.sales_deal_id = None
    contact_id = 7239
    bitrix._mock_leads[lead_id]["CONTACT_ID"] = contact_id
    bitrix._mock_leads[lead_id].update(
        {
            settings.bitrix_field_client_email: "orphan@test.com",
            settings.bitrix_field_installment_count: 2,
            settings.bitrix_field_installment_1: "1000",
            settings.bitrix_field_installment_1_date: "2026-01-01",
            settings.bitrix_field_installment_2: "9000",
            settings.bitrix_field_installment_2_due_date: (
                date.today() + timedelta(days=1)
            ).isoformat(),
        }
    )
    workflow.bitrix_lead_payload = dict(bitrix._mock_leads[lead_id])
    workflow.installment_notices_sent = None

    sales_id = 252410
    finance_id = 252416
    bitrix._mock_deals[sales_id] = {
        "ID": sales_id,
        "LEAD_ID": lead_id,
        "CONTACT_ID": contact_id,
        "TITLE": "Sales",
        "CATEGORY_ID": settings.bitrix_sales_pipeline_id or "16",
    }
    bitrix._mock_deals[finance_id] = {
        "ID": finance_id,
        "LEAD_ID": None,
        "CONTACT_ID": contact_id,
        "TITLE": "Finance",
        "CATEGORY_ID": "44",
        "STAGE_ID": settings.bitrix_finance_generate_link_stage_id,
    }
    db_session.commit()

    response = client.post(
        "/webhooks/bitrix24/installment-due?installment=2",
        data={
            "document_id[0]": "crm",
            "document_id[1]": "CCrmDocumentDeal",
            "document_id[2]": f"DEAL_{finance_id}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["installment_number"] == 2

    db_session.refresh(workflow)
    assert workflow.finance_deal_id == finance_id
