"""Tests for terms and conditions gate."""

from decimal import Decimal


def test_terms_page_has_no_customer_data(client, seed_lead):
    seed_lead(101)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 101, "customer_email": "secret@example.com", "total_amount": "5000"},
    )
    token = response.json()["token"]

    page = client.get(f"/payment/{token}")
    assert page.status_code == 200
    assert "Terms and Conditions" in page.text
    assert "secret@example.com" not in page.text
    assert "5000" not in page.text
    assert "checkbox" in page.text.lower() or "accepted" in page.text.lower()


def test_cannot_proceed_without_acceptance(client, seed_lead):
    seed_lead(102)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 102, "customer_email": "customer@example.com"},
    )
    token = response.json()["token"]

    reject = client.post(f"/payment/{token}/accept", data={}, follow_redirects=False)
    assert reject.status_code == 400


def test_acceptance_records_and_redirects(client, seed_lead):
    seed_lead(103)
    response = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 103, "customer_email": "customer@example.com"},
    )
    token = response.json()["token"]

    accept = client.post(
        f"/payment/{token}/accept",
        data={"accepted": "yes"},
        follow_redirects=False,
    )
    assert accept.status_code == 303
    assert "paymob.com" in accept.headers["location"]
