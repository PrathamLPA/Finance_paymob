"""Course seat assignment on the payment page."""

from decimal import Decimal

from app.integrations.factory import get_bitrix_client
from app.services.course_seats import (
    courses_from_product_rows,
    participants_for_buyer,
    total_seats,
    validate_participants,
)
from tests.conftest import SAMPLE_REGISTRANT


def test_courses_from_product_rows_sums_quantity():
    courses = courses_from_product_rows(
        [
            {"productId": 10, "productName": "PMP", "quantity": 2, "price": 1000},
            {"productId": 20, "productName": "Excel", "quantity": 1, "price": 500},
            {"productId": 10, "productName": "PMP", "quantity": 1, "price": 1000},
        ]
    )
    by_id = {c["product_id"]: c for c in courses}
    assert by_id[10]["quantity"] == 3
    assert by_id[20]["quantity"] == 1
    assert total_seats(courses) == 4


def test_validate_participants_requires_exact_seat_fill():
    courses = [
        {"product_id": 10, "product_name": "PMP", "quantity": 2},
        {"product_id": 20, "product_name": "Excel", "quantity": 1},
    ]
    assert validate_participants(courses, []) is not None
    assert validate_participants(
        courses,
        [
            {"name": "A", "email": "a@test.com", "product_id": 10},
            {"name": "B", "email": "b@test.com", "product_id": 10},
        ],
    ) is not None
    assert (
        validate_participants(
            courses,
            [
                {"name": "A", "email": "a@test.com", "product_id": 10},
                {"name": "B", "email": "b@test.com", "product_id": 10},
                {"name": "C", "email": "c@test.com", "product_id": 20},
            ],
        )
        is None
    )


def test_payment_api_returns_lead_courses(client, seed_lead):
    seed_lead(501, amount=Decimal("3000"))
    bitrix = get_bitrix_client()
    bitrix.seed_lead_products(
        501,
        [
            {"productId": 77, "productName": "PMP Professional", "quantity": 2, "price": 1500},
            {"productId": 88, "productName": "Excel Advanced", "quantity": 1, "price": 500},
        ],
    )

    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": 501,
            "customer_email": "buyer@test.com",
            "customer_name": "Buyer",
            "total_amount": "3000",
        },
    )
    assert link.status_code == 200
    token = link.json()["token"]

    response = client.get(f"/api/payment/{token}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_seats"] == 3
    names = {c["product_name"] for c in payload["courses"]}
    assert "PMP Professional" in names
    assert "Excel Advanced" in names


def test_participants_for_buyer_fills_every_seat():
    courses = [
        {"product_id": 10, "product_name": "PMP", "quantity": 2},
        {"product_id": 20, "product_name": "Excel", "quantity": 1},
    ]
    people = participants_for_buyer(courses, name="Buyer", email="buyer@test.com")
    assert len(people) == 3
    assert {p["name"] for p in people} == {"Buyer"}
    assert validate_participants(courses, people) is None


def _link_with_two_seats(client, seed_lead, lead_id: int) -> str:
    seed_lead(lead_id, amount=Decimal("2000"))
    get_bitrix_client().seed_lead_products(
        lead_id,
        [{"productId": 91, "productName": "PMP", "quantity": 2, "price": 1000}],
    )
    link = client.post(
        "/api/dev/send-payment-link",
        json={
            "lead_id": lead_id,
            "customer_email": "buyer@test.com",
            "customer_name": "Buyer",
            "total_amount": "2000",
        },
    )
    return link.json()["token"]


def test_accept_for_someone_else_requires_participants(client, seed_lead):
    token = _link_with_two_seats(client, seed_lead, 502)

    missing = client.post(
        f"/api/payment/{token}/accept",
        json={**SAMPLE_REGISTRANT, "course_for": "someone_else", "accepted": True},
    )
    assert missing.status_code == 400

    ok = client.post(
        f"/api/payment/{token}/accept",
        json={
            **SAMPLE_REGISTRANT,
            "course_for": "someone_else",
            "accepted": True,
            "participants": [
                {"name": "Alice", "email": "alice@test.com", "product_id": 91},
                {"name": "Bob", "email": "bob@test.com", "product_id": 91},
            ],
        },
    )
    assert ok.status_code == 200
    assert "checkout_url" in ok.json()


def test_accept_for_self_skips_candidate_entry(client, seed_lead, db_session):
    from sqlalchemy import select

    from app.models.terms_acceptance import TermsAcceptance

    token = _link_with_two_seats(client, seed_lead, 503)

    response = client.post(
        f"/api/payment/{token}/accept",
        json={**SAMPLE_REGISTRANT, "course_for": "self", "accepted": True},
    )
    assert response.status_code == 200

    acceptance = db_session.scalars(select(TermsAcceptance)).all()[-1]
    assert len(acceptance.participants_json) == 2
    assert {p["name"] for p in acceptance.participants_json} == {
        SAMPLE_REGISTRANT["registrant_name"]
    }
