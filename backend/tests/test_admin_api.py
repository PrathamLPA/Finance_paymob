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
