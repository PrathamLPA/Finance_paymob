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
    assert "secret@example.com" not in str(data)
    assert data["total_amount"] == "5000.00"
    assert data["remaining_balance"] == "5000.00"
    assert data["minimum_amount"] == "2500.00"


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


def test_partial_amount_is_accepted_above_minimum(client, seed_lead):
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

    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, "payment_amount": "2500", **SAMPLE_REGISTRANT},
    )
    assert accept.status_code == 200

    status = client.get(f"/api/payment/{token}")
    assert status.json()["remaining_balance"] == "5000.00"


def test_amount_below_minimum_is_rejected(client, seed_lead):
    seed_lead(105)
    response = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": 105,
            "customer_email": "customer@example.com",
            "customer_name": "Customer",
            "total_amount": "5000",
        },
    )
    token = response.json()["token"]

    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, "payment_amount": "100", **SAMPLE_REGISTRANT},
    )
    assert accept.status_code == 400
    assert "2500.00" in accept.json()["detail"]


def test_amount_above_balance_is_rejected(client, seed_lead):
    seed_lead(106)
    response = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": 106,
            "customer_email": "customer@example.com",
            "customer_name": "Customer",
            "total_amount": "5000",
        },
    )
    token = response.json()["token"]

    accept = client.post(
        f"/api/payment/{token}/accept",
        json={"accepted": True, "payment_amount": "9000", **SAMPLE_REGISTRANT},
    )
    assert accept.status_code == 400
