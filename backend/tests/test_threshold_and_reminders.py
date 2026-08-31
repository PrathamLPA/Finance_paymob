"""Tests for payment threshold unlock and reminders."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import STATUS_PARTIAL, STATUS_THRESHOLD_MET, CustomerWorkflow
from app.services.reminder_service import ReminderService
from tests.conftest import SAMPLE_REGISTRANT


def _pay(client, lead_id: int, amount: str, email: str = "threshold@test.com"):
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": lead_id, "customer_email": email, "customer_name": "Threshold User", "total_amount": "1000"},
    )
    token = link.json()["token"]
    merchant_reference = link.json()["merchant_reference"]
    client.post(f"/api/payment/{token}/accept", json={"accepted": True, **SAMPLE_REGISTRANT})
    return client.post(
        "/api/dev/simulate-paymob-webhook",
        json={"merchant_reference": merchant_reference, "amount": amount},
    )


def test_partial_payment_below_threshold_keeps_reminders(client, seed_lead, db_session):
    seed_lead(301, email="threshold@test.com", amount=Decimal("1000"))
    response = _pay(client, 301, "300")
    assert response.status_code == 200
    data = response.json()
    assert data["payment_status"] == STATUS_PARTIAL
    assert data["payment_percentage"] == "30.00"
    assert data["reminders_enabled"] is True

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 301))
    assert workflow is not None
    assert workflow.threshold_met_at is None


def test_threshold_payment_unlocks_finance_stage_and_stops_reminders(client, seed_lead, db_session):
    seed_lead(302, email="unlock@test.com", amount=Decimal("1000"))
    response = _pay(client, 302, "500", email="unlock@test.com")
    assert response.status_code == 200
    data = response.json()
    assert data["payment_status"] == STATUS_THRESHOLD_MET
    assert data["payment_percentage"] == "50.00"
    assert data["reminders_enabled"] is False

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 302))
    assert workflow is not None
    assert workflow.threshold_met_at is not None

    bitrix = get_bitrix_client()
    deal = bitrix._mock_deals[workflow.finance_deal_id]
    assert deal["STAGE_ID"] == "FINANCE_THRESHOLD_MET"
    assert deal.get("UF_CRM_PAYMENT_PERCENTAGE") == "50.00"
    assert deal.get("UF_CRM_PAYMENT_STATUS") == STATUS_THRESHOLD_MET


def test_registrant_details_sync_to_workflow(client, seed_lead, db_session):
    seed_lead(303, email="old@test.com", amount=Decimal("1000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 303, "customer_email": "old@test.com", "customer_name": "Old", "total_amount": "1000"},
    )
    token = link.json()["token"]
    client.post(
        f"/api/payment/{token}/accept",
        json={
            "accepted": True,
            "course_for": "someone_else",
            "registrant_name": "New Registrant",
            "registrant_email": "new@test.com",
            "registrant_phone": "+971511111111",
        },
    )
    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 303))
    assert workflow.customer_name == "New Registrant"
    assert workflow.customer_email == "new@test.com"
    assert workflow.customer_phone == "+971511111111"


def test_process_reminders_sends_for_due_workflows(client, seed_lead, db_session):
    seed_lead(304, email="remind@test.com", amount=Decimal("1000"))
    _pay(client, 304, "100", email="remind@test.com")

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 304))
    assert workflow is not None
    workflow.last_reminder_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db_session.commit()

    email_client = get_email_client()
    before = len(email_client.sent_emails)

    result = client.post("/api/dev/process-reminders")
    assert result.status_code == 200
    body = result.json()
    assert body["sent"] >= 1
    assert len(email_client.sent_emails) > before

    db_session.refresh(workflow)
    assert workflow.reminder_count >= 1


def test_expired_unpaid_link_is_refreshed_immediately(client, seed_lead, db_session):
    """When the only payment link expires and balance remains, share a new one."""
    from app.models.payment_session import SESSION_EXPIRED, SESSION_PENDING

    seed_lead(305, email="expired@test.com", amount=Decimal("1000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": 305,
            "customer_email": "expired@test.com",
            "customer_name": "Expired User",
            "total_amount": "1000",
        },
    )
    assert link.status_code == 200
    old_token = link.json()["token"]

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 305))
    assert workflow is not None
    session = next(s for s in workflow.payment_sessions if s.token == old_token)
    session.status = SESSION_EXPIRED
    session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    # Do not wait for the 24h reminder interval.
    workflow.last_reminder_at = datetime.now(timezone.utc)
    db_session.commit()

    service = ReminderService(db_session)
    assert service._needs_expired_link_refresh(workflow) is True
    assert workflow in service.workflows_due_for_reminder()

    email_client = get_email_client()
    before = len(email_client.sent_emails)
    bitrix = get_bitrix_client()
    comments_before = len(bitrix._mock_comments.get(("LEAD", 305), []))

    result = client.post("/api/dev/process-reminders")
    assert result.status_code == 200
    assert result.json()["sent"] >= 1
    assert len(email_client.sent_emails) > before

    db_session.refresh(workflow)
    active = [s for s in workflow.payment_sessions if s.status == SESSION_PENDING]
    assert active
    assert active[0].token != old_token
    comments = bitrix._mock_comments.get(("LEAD", 305), [])
    assert len(comments) > comments_before
    assert any("no longer valid" in c["COMMENT"] or "Payment link:" in c["COMMENT"] for c in comments)


def test_reminder_paymob_invalid_email_notifies_bitrix(client, seed_lead, db_session):
    """When Paymob rejects billing email, Bitrix gets a timeline comment and agent alert."""
    from unittest.mock import AsyncMock, patch

    seed_lead(320, email="good@test.com", amount=Decimal("1000"))
    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": 320,
            "customer_email": "good@test.com",
            "customer_name": "Bad Email User",
            "total_amount": "1000",
        },
    )
    assert link.status_code == 200

    workflow = db_session.scalar(select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == 320))
    assert workflow is not None
    workflow.customer_email = "not-a-valid-email"
    workflow.last_reminder_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db_session.commit()

    bitrix = get_bitrix_client()
    comments_before = len(bitrix._mock_comments.get(("LEAD", 320), []))
    notifications_before = len(bitrix._mock_notifications)

    paymob_error = ValueError(
        'Paymob intention failed (400): {"billing_data":{"email":["Enter a valid email address."]}}'
    )
    with patch(
        "app.services.payment_session_service.get_paymob_client",
    ) as mock_factory:
        mock_paymob = AsyncMock()
        mock_paymob.create_payment_session.side_effect = paymob_error
        mock_factory.return_value = mock_paymob

        result = client.post("/api/dev/process-reminders")

    assert result.status_code == 200
    body = result.json()
    assert body["due"] >= 1
    assert body["sent"] == 0
    assert any("320" in err for err in body["errors"])

    comments = bitrix._mock_comments.get(("LEAD", 320), [])
    assert len(comments) > comments_before
    assert any("invalid customer email" in c["COMMENT"].lower() for c in comments)
    assert len(bitrix._mock_notifications) > notifications_before
    assert any(
        "invalid customer email" in n["message"].lower() for n in bitrix._mock_notifications
    )
