"""Tests for terms and conditions gate (API)."""

from tests.conftest import SAMPLE_REGISTRANT


def test_payment_api_exposes_amounts_but_no_customer_data(client, seed_lead):
    seed_lead(101)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 101, "customer_email": "secret@example.com", "total_amount": "5000"},
    )
    token = response.json()["token"]

    page = client.get(f"/api/payment/{token}")
    assert page.status_code == 200
    data = page.json()
    assert "terms_html" in data
    assert "Payment Terms" in data["terms_html"] or "Terms" in data["terms_html"]
    assert data["total_amount"] == "5000.00"
    assert data["remaining_balance"] == "5000.00"
    # Empty installment fields → full amount, locked (customer cannot edit)
    assert data["payment_amount"] == "5000.00"
    assert data["amount_locked"] is True
    assert data["allows_partial"] is False
    assert data["charge_source"] == "full"


def test_cannot_proceed_without_acceptance(client, seed_lead):
    seed_lead(102)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 102, "customer_email": "customer@example.com"},
    )
    token = response.json()["token"]

    reject = client.post(f"/api/payment/{token}/accept", json={})
    assert reject.status_code == 400


def test_acceptance_returns_checkout_url(client, seed_lead):
    seed_lead(103)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 103, "customer_email": "customer@example.com"},
    )
    token = response.json()["token"]

    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **SAMPLE_REGISTRANT},
    )
    assert accept.status_code == 200
    assert "paymob.com" in accept.json()["checkout_url"]


def test_terms_email_goes_to_payment_link_recipient_not_registrant(db_session, monkeypatch):
    """Terms confirmation must match Payment Request inbox, not a different form email."""
    import asyncio
    from decimal import Decimal

    from datetime import datetime, timedelta, timezone

    from app.integrations.factory import get_email_client
    from app.models.customer_workflow import CustomerWorkflow
    from app.models.payment_session import (
        CHANNEL_ONLINE,
        SESSION_TERMS_ACCEPTED,
        SOURCE_LEAD,
        PaymentSession,
    )
    from app.services.terms_service import TermsService

    workflow = CustomerWorkflow(
        bitrix_lead_id=113,
        customer_email="agent-filled@test.com",
        customer_name="Agent Filled",
        total_amount=Decimal("5000.00"),
        amount_paid=Decimal("0.00"),
        currency="AED",
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    session = PaymentSession(
        workflow_id=workflow.id,
        token="terms-email-test-token",
        source_type=SOURCE_LEAD,
        source_id=113,
        charge_amount=Decimal("5000.00"),
        charge_source="full",
        amount_locked=True,
        currency="AED",
        channel=CHANNEL_ONLINE,
        status=SESSION_TERMS_ACCEPTED,
        merchant_reference="WF-terms-email",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: db_session)
    # run_acceptance_side_effects closes the session in finally — keep test session open.
    original_close = db_session.close
    monkeypatch.setattr(db_session, "close", lambda: None)

    email_client = get_email_client()
    before = len(email_client.sent_emails)

    asyncio.run(
        TermsService.run_acceptance_side_effects(
            session_id=session.id,
            workflow_id=workflow.id,
            course_for="self",
            registrant_name="Agent Filled",
            registrant_email="agent-filled@test.com",
            registrant_phone="+971500000113",
            participants=None,
            terms_to_email="link-recipient@test.com",
        )
    )

    monkeypatch.setattr(db_session, "close", original_close)

    terms_mails = [
        m
        for m in email_client.sent_emails[before:]
        if m.get("subject") == "Terms and Conditions Acceptance"
    ]
    assert terms_mails, "expected Terms acceptance email"
    assert terms_mails[-1]["to"] == "link-recipient@test.com"


def test_accept_without_payment_mode_uses_bitrix_online(client, seed_lead):
    seed_lead(110)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 110, "customer_email": "customer@example.com"},
    )
    token = response.json()["token"]
    body = {**SAMPLE_REGISTRANT}
    body.pop("payment_mode", None)
    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **body},
    )
    assert accept.status_code == 200
    assert "checkout_url" in accept.json()


def test_accept_bank_transfer_returns_receipt_url(client, seed_lead):
    from app.config import get_settings
    from app.integrations.factory import get_bitrix_client

    seed_lead(111)
    settings = get_settings()
    bitrix = get_bitrix_client()
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 111, "customer_email": "customer@example.com"},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    bitrix._mock_leads[111][settings.bitrix_field_payment_1_mode] = "5778"
    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **{k: v for k, v in SAMPLE_REGISTRANT.items() if k != "payment_mode"}},
    )
    assert accept.status_code == 200
    assert "/receipt" in accept.json()["checkout_url"]


def test_accept_cash_returns_thank_you_url(client, seed_lead):
    from app.config import get_settings
    from app.integrations.factory import get_bitrix_client

    seed_lead(112)
    settings = get_settings()
    bitrix = get_bitrix_client()
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 112, "customer_email": "customer@example.com"},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    # Bitrix Payment Mode drives the channel at accept time.
    bitrix._mock_leads[112][settings.bitrix_field_payment_1_mode] = "5774"
    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, **{k: v for k, v in SAMPLE_REGISTRANT.items() if k != "payment_mode"}},
    )
    assert accept.status_code == 200
    assert "thank-you" in accept.json()["checkout_url"]


def test_blank_payment_mode_comments_on_bitrix(client, seed_lead):
    from app.config import get_settings
    from app.integrations.factory import get_bitrix_client

    seed_lead(113)
    settings = get_settings()
    bitrix = get_bitrix_client()
    # Explicitly blank installment-1 mode
    bitrix._mock_leads[113].pop(settings.bitrix_field_payment_1_mode, None)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 113, "customer_email": "customer@example.com"},
    )
    assert response.status_code == 200
    comments = bitrix._mock_comments.get(("LEAD", 113), [])
    assert any(
        "Payment Mode is not set for Installment 1" in (c.get("COMMENT") or c.get("comment") or str(c))
        for c in comments
    )


def test_locked_amount_ignores_customer_choice(client, seed_lead):
    seed_lead(104)
    response = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": 104,
            "customer_email": "customer@example.com",
            "customer_name": "Customer",
            "total_amount": "5000",
        },
    )
    token = response.json()["token"]

    # Customer tries to pay less; locked full charge wins.
    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, "payment_amount": "100", **SAMPLE_REGISTRANT},
    )
    assert accept.status_code == 200

    status = client.get(f"/api/payment/{token}")
    assert status.json()["remaining_balance"] == "5000.00"


def test_second_payment_reuses_first_payment_customer_details(client, db_session):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from app.models.customer_workflow import CustomerWorkflow
    from app.models.payment_session import (
        SESSION_COMPLETED,
        SESSION_PENDING,
        SOURCE_FINANCE_DEAL,
        SOURCE_LEAD,
        PaymentSession,
    )
    from app.models.terms_acceptance import TermsAcceptance

    workflow = CustomerWorkflow(
        bitrix_lead_id=114,
        finance_deal_id=9001,
        # Simulates a later Bitrix deal refresh changing workflow display fields.
        customer_name="Bitrix Refreshed Name",
        customer_email="bitrix@test.com",
        customer_phone="+971599999998",
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("50.00"),
        currency="AED",
    )
    db_session.add(workflow)
    db_session.flush()
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    first = PaymentSession(
        workflow_id=workflow.id,
        token="first-payment-details-token",
        source_type=SOURCE_LEAD,
        source_id=114,
        charge_amount=Decimal("50.00"),
        charge_source="installment_1",
        amount_locked=True,
        installment_number=1,
        currency="AED",
        merchant_reference="WF-FIRST-DETAILS",
        status=SESSION_COMPLETED,
        expires_at=expires,
    )
    second = PaymentSession(
        workflow_id=workflow.id,
        token="second-payment-details-token",
        source_type=SOURCE_FINANCE_DEAL,
        source_id=9001,
        charge_amount=Decimal("50.00"),
        charge_source="installment_2",
        amount_locked=True,
        installment_number=2,
        currency="AED",
        merchant_reference="WF-SECOND-DETAILS",
        status=SESSION_PENDING,
        expires_at=expires,
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(
        TermsAcceptance(
            payment_session_id=first.id,
            terms_version="1.0",
            course_for="self",
            registrant_name="First Payer",
            registrant_email="first@test.com",
            registrant_phone="+971500001114",
        )
    )
    db_session.commit()

    page = client.get(f"/api/payment/{second.token}")
    assert page.status_code == 200
    context = page.json()
    assert context["is_subsequent_payment"] is True
    assert context["customer_name"] == "First Payer"
    assert context["customer_email"] == "first@test.com"
    assert context["customer_phone"] == "+971500001114"

    accepted = client.post(
        f"/api/payment/{second.token}/accept",
        json={
            "accepted": True,
            "course_for": "someone_else",
            "registrant_name": "Changed Name",
            "registrant_email": "changed@test.com",
            "registrant_phone": "+971599999999",
            "payment_mode": "card",
        },
    )
    assert accepted.status_code == 200

    db_session.refresh(workflow)
    assert workflow.customer_name == "First Payer"
    assert workflow.customer_email == "first@test.com"
    assert workflow.customer_phone == "+971500001114"
