"""Tests for terms and conditions gate (API)."""

from tests.conftest import SAMPLE_REGISTRANT


def test_payment_api_has_no_customer_data(client, seed_lead):
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
    assert "5000" not in str(data)


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
