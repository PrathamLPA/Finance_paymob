"""Tests for real Bitrix outbound webhook payloads."""

from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.integrations.factory import get_bitrix_client
from app.models.customer_workflow import CustomerWorkflow
from tests.conftest import SAMPLE_REGISTRANT


def _finance_deal(client, seed_lead, lead_id: int) -> int:
    seed_lead(lead_id, email="bitrix@test.com", amount=Decimal("10000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": lead_id, "customer_email": "bitrix@test.com", "total_amount": "10000"},
    ).json()
    client.post(f"/api/payment/{link['token']}/accept", json={"accepted": True, **SAMPLE_REGISTRANT})
    payment = client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": link["merchant_reference"], "amount": "1000"},
    ).json()
    return payment["finance_deal_id"]


def test_form_encoded_deal_update_generates_link(client, seed_lead):
    settings = get_settings()
    deal_id = _finance_deal(client, seed_lead, 401)

    bitrix = get_bitrix_client()
    bitrix._mock_deals[deal_id]["STAGE_ID"] = settings.bitrix_finance_generate_link_stage_id
    bitrix._mock_deals[deal_id].pop(settings.bitrix_field_payment_link, None)

    response = client.post(
        "/webhooks/bitrix24",
        data={
            "event": "ONCRMDEALUPDATE",
            "data[FIELDS][ID]": str(deal_id),
            "ts": "1754000000",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["deal_id"] == deal_id
    assert bitrix._mock_deals[deal_id][settings.bitrix_field_payment_link] == body["payment_url"]


def test_deal_update_in_other_stage_is_ignored(client, seed_lead):
    deal_id = _finance_deal(client, seed_lead, 402)

    bitrix = get_bitrix_client()
    bitrix._mock_deals[deal_id]["STAGE_ID"] = "SOME_OTHER_STAGE"

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMDEALUPDATE", "data[FIELDS][ID]": str(deal_id)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "not_generate_link_stage"


def test_repeat_update_does_not_create_second_link(client, seed_lead):
    settings = get_settings()
    deal_id = _finance_deal(client, seed_lead, 403)

    bitrix = get_bitrix_client()
    bitrix._mock_deals[deal_id]["STAGE_ID"] = settings.bitrix_finance_generate_link_stage_id
    bitrix._mock_deals[deal_id].pop(settings.bitrix_field_payment_link, None)

    first = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMDEALUPDATE", "data[FIELDS][ID]": str(deal_id)},
    ).json()
    second = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMDEALUPDATE", "data[FIELDS][ID]": str(deal_id)},
    ).json()

    assert first["status"] == "processed"
    assert second["status"] == "ignored"
    assert second["reason"] == "payment_link_already_active"
    assert second["payment_url"] == first["payment_url"]


def test_application_token_is_validated(client, seed_lead, monkeypatch):
    from app.config import Settings

    deal_id = _finance_deal(client, seed_lead, 404)

    get_settings.cache_clear()
    monkeypatch.setenv("BITRIX_WEBHOOK_SECRET", "secret-token")
    assert Settings().bitrix_webhook_secret == "secret-token"

    rejected = client.post(
        "/webhooks/bitrix24",
        data={
            "event": "ONCRMDEALUPDATE",
            "data[FIELDS][ID]": str(deal_id),
            "auth[application_token]": "wrong-token",
        },
    )
    assert rejected.status_code == 401

    accepted = client.post(
        "/webhooks/bitrix24",
        data={
            "event": "ONCRMDEALUPDATE",
            "data[FIELDS][ID]": str(deal_id),
            "auth[application_token]": "secret-token",
        },
    )
    assert accepted.status_code == 200

    get_settings.cache_clear()


def test_lead_update_fetches_and_stores_complete_lead(client, seed_lead, db_session):
    settings = get_settings()
    seed_lead(405, email="full-lead@test.com", amount=Decimal("2500"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[405].update(
        {
            "STATUS_ID": settings.bitrix_lead_payment_stage_id,
            "PHONE": [{"VALUE": "+971501234567", "VALUE_TYPE": "WORK"}],
            "UF_CRM_COURSE": "Python",
            "SOURCE_ID": "WEB",
        }
    )

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "405"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 405)
    )
    assert workflow is not None
    assert workflow.bitrix_lead_stage_id == settings.bitrix_lead_payment_stage_id
    assert workflow.bitrix_lead_payload["UF_CRM_COURSE"] == "Python"
    assert workflow.bitrix_lead_payload["SOURCE_ID"] == "WEB"
    assert workflow.customer_email == "full-lead@test.com"
    assert workflow.customer_phone == "+971501234567"
    assert workflow.total_amount == Decimal("2500")
    assert workflow.lead_synced_at is not None


def test_automation_robot_payload_generates_link(client, seed_lead, db_session):
    """CRM automation robots send document_id[] instead of event/data[FIELDS]."""
    settings = get_settings()
    seed_lead(407, email="robot@test.com", amount=Decimal("3000"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[407]["STATUS_ID"] = settings.bitrix_lead_payment_stage_id

    response = client.post(
        "/webhooks/bitrix24",
        data={
            "document_id[0]": "crm",
            "document_id[1]": "CCrmDocumentLead",
            "document_id[2]": "LEAD_407",
            "code": "bitrix24.webhook",
            "ts": "1754000000",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed", body
    assert body["lead_id"] == 407
    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 407)
    )
    assert workflow is not None


def test_lead_update_outside_payment_stage_is_not_imported(client, seed_lead, db_session):
    seed_lead(406, email="ignored@test.com", amount=Decimal("1000"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[406]["STATUS_ID"] = "NEW"

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "406"},
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "not_payment_stage"
    workflow = db_session.scalar(
        select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 406)
    )
    assert workflow is None


def test_lead_without_amount_returns_error_not_crash(client, seed_lead, db_session):
    settings = get_settings()
    seed_lead(408, email="no-amount@test.com", amount=Decimal("0"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[408]["STATUS_ID"] = settings.bitrix_lead_payment_stage_id
    bitrix._mock_leads[408]["OPPORTUNITY"] = ""

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "408"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "no payment amount" in response.json()["reason"]


def test_lead_amount_read_from_custom_field(client, seed_lead, monkeypatch):
    from app.config import Settings

    settings = get_settings()
    seed_lead(409, email="custom-amount@test.com", amount=Decimal("0"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[409]["STATUS_ID"] = settings.bitrix_lead_payment_stage_id
    bitrix._mock_leads[409]["OPPORTUNITY"] = ""
    bitrix._mock_leads[409]["UF_CRM_PROSPECT_VALUE"] = "3,500.00"

    monkeypatch.setenv("BITRIX_FIELD_LEAD_AMOUNT", "UF_CRM_PROSPECT_VALUE")
    get_settings.cache_clear()
    bitrix.settings = Settings()

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "409"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    bitrix.settings = settings
    get_settings.cache_clear()


def test_lead_payment_uses_installment_1_amount(client, seed_lead, db_session, monkeypatch):
    monkeypatch.setenv("BITRIX_FIELD_INSTALLMENT_1", "UF_CRM_INSTALLMENT_1")
    monkeypatch.setenv("BITRIX_FIELD_INSTALLMENT_COUNT", "UF_CRM_INSTALLMENT_COUNT")
    monkeypatch.setenv("BITRIX_PRICE_GATE_ENABLED", "false")
    get_settings.cache_clear()

    settings = get_settings()
    seed_lead(411, email="installment@test.com", amount=Decimal("5500"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[411].update(
        {
            "STATUS_ID": settings.bitrix_lead_payment_stage_id,
            "UF_CRM_INSTALLMENT_1": "1500",
            "UF_CRM_INSTALLMENT_COUNT": "3",
        }
    )

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "411"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"

    token = body["payment_url"].rstrip("/").rsplit("/", 1)[-1]
    session = client.get(f"/api/payment/{token}").json()
    assert session["payment_amount"] == "1500.00"
    assert session["amount_locked"] is True
    assert session["allows_partial"] is False
    assert session["charge_source"] == "installment_1"
    assert session["charge_label"] == "Installment 1"

    get_settings.cache_clear()


def test_lead_payment_link_posts_timeline_comment(client, seed_lead):
    settings = get_settings()
    seed_lead(410, email="comment@test.com", amount=Decimal("1500"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[410]["STATUS_ID"] = settings.bitrix_lead_payment_stage_id

    response = client.post(
        "/webhooks/bitrix24",
        data={"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "410"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    comments = bitrix._mock_comments.get(("LEAD", 410), [])
    assert len(comments) == 1
    assert response.json()["payment_url"] in comments[0]["COMMENT"]


def test_repeat_lead_update_reuses_active_payment_link(client, seed_lead):
    settings = get_settings()
    seed_lead(407, email="repeat-lead@test.com", amount=Decimal("1000"))
    bitrix = get_bitrix_client()
    bitrix._mock_leads[407]["STATUS_ID"] = settings.bitrix_lead_payment_stage_id
    payload = {"event": "ONCRMLEADUPDATE", "data[FIELDS][ID]": "407"}

    first = client.post("/webhooks/bitrix24", data=payload).json()
    second = client.post("/webhooks/bitrix24", data=payload).json()

    assert first["status"] == "processed"
    assert second["status"] == "ignored"
    assert second["reason"] == "payment_link_already_active"
    assert second["payment_url"] == first["payment_url"]
