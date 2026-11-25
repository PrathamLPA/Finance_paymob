"""Login lockout, locked-down dev endpoints, upload content checks, security headers."""

import os

import pytest

from app.config import get_settings
from app.models.staff_user import ROLE_ADMIN, ROLE_MANAGER, StaffUser
from app.services import login_throttle
from app.services.proof_storage import content_matches_type, extension_for
from app.services.staff_auth import hash_password


@pytest.fixture(autouse=True)
def _secret_and_reset(monkeypatch):
    monkeypatch.setitem(os.environ, "STAFF_JWT_SECRET", "test-secret-for-security")
    get_settings.cache_clear()
    login_throttle.reset()
    yield
    login_throttle.reset()
    get_settings.cache_clear()


def _user(db, email, role=ROLE_MANAGER, password="secret1"):
    db.add(
        StaffUser(
            email=email,
            name=email.split("@")[0],
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
    )
    db.commit()


def test_account_locks_after_repeated_wrong_passwords(client, db_session):
    _user(db_session, "fin@example.com")
    for _ in range(5):
        res = client.post("/api/staff/login", json={"email": "fin@example.com", "password": "wrong"})
        assert res.status_code == 401
    # Even the right password is refused while locked.
    locked = client.post("/api/staff/login", json={"email": "fin@example.com", "password": "secret1"})
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers
    # Another account from the same place is not locked by this one.
    _user(db_session, "other@example.com")
    ok = client.post("/api/staff/login", json={"email": "other@example.com", "password": "secret1"})
    assert ok.status_code == 200


def test_successful_login_clears_the_failure_count(client, db_session):
    _user(db_session, "fin@example.com")
    for _ in range(3):
        client.post("/api/staff/login", json={"email": "fin@example.com", "password": "wrong"})
    assert client.post(
        "/api/staff/login", json={"email": "fin@example.com", "password": "secret1"}
    ).status_code == 200
    for _ in range(3):
        client.post("/api/staff/login", json={"email": "fin@example.com", "password": "wrong"})
    assert client.post(
        "/api/staff/login", json={"email": "fin@example.com", "password": "secret1"}
    ).status_code == 200


def test_dev_endpoints_need_an_admin_in_production(client, db_session, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    # Open to the internet before; now rejected without a login.
    assert client.get("/api/dev/zoho/organizations").status_code == 401
    assert client.post("/api/dev/process-reminders").status_code == 401

    _user(db_session, "fin@example.com", role=ROLE_MANAGER)
    manager = client.post(
        "/api/staff/login", json={"email": "fin@example.com", "password": "secret1"}
    ).json()["token"]
    forbidden = client.get(
        "/api/dev/zoho/organizations", headers={"Authorization": f"Bearer {manager}"}
    )
    assert forbidden.status_code == 403

    _user(db_session, "admin@example.com", role=ROLE_ADMIN)
    admin = client.post(
        "/api/staff/login", json={"email": "admin@example.com", "password": "secret1"}
    ).json()["token"]
    allowed = client.get(
        "/api/dev/zoho/organizations", headers={"Authorization": f"Bearer {admin}"}
    )
    assert allowed.status_code != 401 and allowed.status_code != 403


def test_responses_carry_security_headers(client):
    res = client.get("/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in res.headers


def test_upload_content_must_match_its_claimed_type():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 20
    pdf = b"%PDF-1.7\n" + b"0" * 20
    webp = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20
    assert content_matches_type("image/png", png)
    assert content_matches_type("image/jpeg", jpeg)
    assert content_matches_type("application/pdf", pdf)
    assert content_matches_type("image/webp", webp)
    # A page or script pretending to be an image is refused.
    assert not content_matches_type("image/png", b"<html><script>alert(1)</script></html>")
    assert not content_matches_type("application/pdf", b"MZ\x90\x00 not a pdf")
    assert not content_matches_type("image/jpeg", png)


def test_stored_extension_comes_from_the_verified_type_not_the_filename():
    assert extension_for("image/png") == ".png"
    assert extension_for("application/pdf") == ".pdf"
    assert extension_for("text/html") == ".bin"
