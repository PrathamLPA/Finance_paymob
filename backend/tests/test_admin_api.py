"""Developer admin API: sign in, see counts, manage people, flip the finance check."""

import os

import pytest

from app.config import get_settings
from app.models.staff_user import ROLE_ADMIN, ROLE_MANAGER, StaffUser
from app.services.staff_auth import hash_password


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setitem(os.environ, "STAFF_JWT_SECRET", "test-secret-for-admin")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_user(db, *, email: str, role: str, password: str = "secret1") -> StaffUser:
    user = StaffUser(
        email=email,
        name=email.split("@")[0].title(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, email: str, password: str = "secret1") -> dict:
    res = client.post("/api/staff/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_full_flow(client, db_session):
    _make_user(db_session, email="admin@example.com", role=ROLE_ADMIN)
    admin = _login(client, "admin@example.com")

    # Lands with the admin role and sees the control numbers.
    me = client.get("/api/staff/me", headers=admin).json()
    assert me["role"] == "admin"
    overview = client.get("/api/staff/admin/overview", headers=admin)
    assert overview.status_code == 200
    body = overview.json()
    assert body["finance_manager_verification"] is False
    assert body["staff"]["admin"] == 1
    assert body["transactions"] == 0

    # Can add a finance manager and an employee.
    created = client.post(
        "/api/staff/admin/people",
        headers=admin,
        json={"email": "fin@example.com", "name": "Fin", "password": "secret1", "role": "manager"},
    )
    assert created.status_code == 200, created.text
    emp = client.post(
        "/api/staff/admin/people",
        headers=admin,
        json={"email": "emp@example.com", "name": "Emp", "password": "secret1", "role": "employee"},
    )
    assert emp.status_code == 200
    people = client.get("/api/staff/admin/people", headers=admin).json()["items"]
    assert {p["email"] for p in people} == {"admin@example.com", "fin@example.com", "emp@example.com"}

    # Can reset a password and deactivate, but never lock themselves out.
    emp_id = emp.json()["id"]
    patched = client.patch(
        f"/api/staff/admin/people/{emp_id}",
        headers=admin,
        json={"password": "newpass1", "is_active": False},
    )
    assert patched.status_code == 200 and patched.json()["is_active"] is False
    assert client.post(
        "/api/staff/login", json={"email": "emp@example.com", "password": "newpass1"}
    ).status_code == 401  # inactive
    self_lock = client.patch(
        f"/api/staff/admin/people/{me['id']}", headers=admin, json={"is_active": False}
    )
    assert self_lock.status_code == 400

    # Can switch the finance check on and off; manager screens still open for admin.
    assert client.put(
        "/api/staff/admin/verification", headers=admin, json={"enabled": True}
    ).json()["finance_manager_verification"] is True
    assert client.get("/api/staff/admin/overview", headers=admin).json()[
        "finance_manager_verification"
    ] is True
    assert client.get("/api/staff/dashboard", headers=admin).status_code == 200
    assert client.get("/api/staff/admin/verifications", headers=admin).status_code == 200
    assert client.put(
        "/api/staff/admin/verification", headers=admin, json={"enabled": False}
    ).json()["finance_manager_verification"] is False


def test_manager_cannot_use_admin_routes_but_can_review(client, db_session):
    _make_user(db_session, email="fin@example.com", role=ROLE_MANAGER)
    manager = _login(client, "fin@example.com")
    assert client.get("/api/staff/admin/overview", headers=manager).status_code == 403
    assert client.get("/api/staff/admin/people", headers=manager).status_code == 403
    assert client.put(
        "/api/staff/admin/verification", headers=manager, json={"enabled": True}
    ).status_code == 403
    # The finance-check queue is for managers.
    assert client.get("/api/staff/admin/verifications", headers=manager).status_code == 200


def test_payment_links_page_lists_links_emails_and_mode(client, db_session):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from app.models.customer_workflow import CustomerWorkflow
    from app.models.email_log import EmailLog
    from app.models.payment_session import PaymentSession

    _make_user(db_session, email="fin@example.com", role=ROLE_MANAGER)
    manager = _login(client, "fin@example.com")

    workflow = CustomerWorkflow(
        bitrix_lead_id=777, customer_name="Sam", customer_email="sam@example.com"
    )
    db_session.add(workflow)
    db_session.commit()
    session = PaymentSession(
        workflow_id=workflow.id,
        token="tok-abc-123",
        source_type="lead",
        source_id=777,
        charge_amount=Decimal("2.10"),
        merchant_reference="WF-1",
        customer_payment_mode="tabby",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(session)
    db_session.add(
        EmailLog(
            to_email="sam@example.com",
            subject="Payment Request",
            body="Pay here: https://x/payment/tok-abc-123",
            status="sent",
        )
    )
    db_session.add(
        EmailLog(to_email="other@example.com", subject="Other", body="no link", status="sent")
    )
    db_session.commit()

    res = client.get("/api/staff/admin/payment-links", headers=manager)
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["links"]) == 1
    link = body["links"][0]
    assert link["lead_id"] == 777
    assert link["chosen_mode"] == "tabby"
    assert link["payment_url"].endswith("/payment/tok-abc-123")
    assert [m["to"] for m in link["emails"]] == ["sam@example.com"]
    assert len(body["emails"]) == 2
    assert body["pending_approvals"] == []
    assert body["price_approvals"] == []

    from app.models.price_approval import PriceApproval

    db_session.add(
        PriceApproval(
            workflow_id=workflow.id,
            bitrix_lead_id=777,
            token="appr-tok-9",
            manager_name="Mona Manager",
            manager_email="mona@example.com",
            notified_via="sendgrid",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    db_session.add(
        EmailLog(
            to_email="mona@example.com",
            subject="Price approval needed",
            body="Review: https://x/approvals/appr-tok-9",
            status="sent",
        )
    )
    db_session.commit()
    approvals = client.get("/api/staff/admin/payment-links", headers=manager).json()["price_approvals"]
    assert len(approvals) == 1
    assert approvals[0]["manager_name"] == "Mona Manager"
    assert approvals[0]["manager_email"] == "mona@example.com"
    assert approvals[0]["approval_url"].endswith("/approvals/appr-tok-9")
    assert [m["to"] for m in approvals[0]["emails"]] == ["mona@example.com"]


def test_data_mode_separates_test_and_live_and_clear_only_touches_active_mode(client, db_session):
    from decimal import Decimal

    from app.models.customer_workflow import CustomerWorkflow
    from app.models.email_log import EmailLog
    from app.models.payment_transaction import PaymentTransaction

    _make_user(db_session, email="admin@example.com", role=ROLE_ADMIN)
    admin = _login(client, "admin@example.com")

    # Fresh installs behave like today: test mode.
    assert client.get("/api/staff/admin/overview", headers=admin).json()["data_mode"] == "test"

    def add_payment(lead_id: int, txn_id: str) -> None:
        wf = CustomerWorkflow(bitrix_lead_id=lead_id, customer_name=f"Lead {lead_id}")
        db_session.add(wf)
        db_session.commit()
        db_session.add(
            PaymentTransaction(
                workflow_id=wf.id,
                transaction_id=txn_id,
                amount=Decimal("10.00"),
                remaining_balance=Decimal("0.00"),
            )
        )
        db_session.commit()

    add_payment(1, "TEST-1")  # stamped test
    assert client.get("/api/staff/admin/overview", headers=admin).json()["transactions"] == 1

    # Switch to production: the test payment disappears from the staff view.
    res = client.put("/api/staff/admin/data-mode", headers=admin, json={"mode": "live"})
    assert res.json()["data_mode"] == "live"
    assert client.get("/api/staff/admin/overview", headers=admin).json()["transactions"] == 0

    add_payment(2, "LIVE-1")  # stamped live
    assert client.get("/api/staff/admin/overview", headers=admin).json()["transactions"] == 1
    db_session.add(EmailLog(to_email="a@b.c", subject="live mail", status="sent"))
    db_session.commit()

    # Clear needs the exact phrase, and only deletes the active (live) mode.
    assert client.post("/api/staff/admin/clear-data", headers=admin, json={"confirm": "yes"}).status_code == 400
    assert client.post(
        "/api/staff/admin/clear-data", headers=admin, json={"confirm": "DELETE LIVE DATA"}
    ).status_code == 200
    assert client.get("/api/staff/admin/overview", headers=admin).json()["transactions"] == 0

    # Back in test mode the test payment is still there.
    client.put("/api/staff/admin/data-mode", headers=admin, json={"mode": "test"})
    assert client.get("/api/staff/admin/overview", headers=admin).json()["transactions"] == 1
    cleared = client.post(
        "/api/staff/admin/clear-data", headers=admin, json={"confirm": "CLEAR TEST DATA"}
    ).json()
    assert cleared["deleted"]["payment_transactions"] == 1
    assert cleared["deleted"]["customer_workflows"] == 1
    assert client.get("/api/staff/admin/overview", headers=admin).json()["transactions"] == 0


def test_data_mode_routes_are_admin_only(client, db_session):
    _make_user(db_session, email="fin@example.com", role=ROLE_MANAGER)
    manager = _login(client, "fin@example.com")
    assert client.put("/api/staff/admin/data-mode", headers=manager, json={"mode": "live"}).status_code == 403
    assert client.post("/api/staff/admin/clear-data", headers=manager, json={"confirm": "x"}).status_code == 403
