"""Editable Terms and Conditions: safe rendering, versions, admin-only, customer view."""

import os

import pytest

from app.config import get_settings
from app.models.staff_user import ROLE_ADMIN, ROLE_MANAGER, StaffUser
from app.services.staff_auth import hash_password
from app.services.terms_render import render_terms_html

LONG = "## Refund Policy\n\n" + "You may ask for a refund within two days of registering. " * 3


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setitem(os.environ, "STAFF_JWT_SECRET", "test-secret-for-terms")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _login(client, db, email, role):
    db.add(
        StaffUser(
            email=email, name=email.split("@")[0], password_hash=hash_password("secret1"),
            role=role, is_active=True,
        )
    )
    db.commit()
    token = client.post("/api/staff/login", json={"email": email, "password": "secret1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_renderer_builds_sections_lists_bold_and_safe_links():
    html = render_terms_html(
        "## One\n\nHello **world**.\n\n- a\n- b\n\n## Two\n\nMail [us](mailto:info@x.org) or [site](https://x.org)."
    )
    assert html.count('<section class="policy-section">') == 2
    assert "<h2>One</h2>" in html and "<h2>Two</h2>" in html
    assert "<strong>world</strong>" in html
    assert "<ul><li>a</li><li>b</li></ul>" in html
    assert 'href="mailto:info@x.org"' in html and 'href="https://x.org"' in html


def test_renderer_never_lets_typed_markup_through():
    html = render_terms_html(
        '## <script>alert(1)</script>\n\n<img src=x onerror=alert(1)> [bad](javascript:alert(1)) '
        '[ok](https://x.org/a"b)'
    )
    assert "<script" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
    # A javascript: address is not turned into a link.
    assert 'href="javascript' not in html


def test_customers_see_the_built_in_text_until_an_admin_publishes(client, db_session):
    body = client.get("/api/payment/terms").json()
    assert body["version"] == get_settings().terms_version
    assert "Refund Policy" in body["html"]
    assert body["published_at"] is None


def test_admin_publishes_a_new_version_and_customers_see_it(client, db_session):
    admin = _login(client, db_session, "admin@example.com", ROLE_ADMIN)
    first = client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG, "note": "Shorter"})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == "1.1"
    second = client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG + "\n\nExtra line."})
    assert second.json()["version"] == "1.2"

    public = client.get("/api/payment/terms").json()
    assert public["version"] == "1.2"
    assert "Extra line." in public["html"]

    state = client.get("/api/staff/admin/terms", headers=admin).json()
    assert state["active"]["version"] == "1.2"
    assert [h["version"] for h in state["history"]] == ["1.2", "1.1"]
    assert [h["is_active"] for h in state["history"]] == [True, False]
    assert state["built_in_content"].startswith("## What information")


def test_publish_rejects_empty_and_unchanged_text(client, db_session):
    admin = _login(client, db_session, "admin@example.com", ROLE_ADMIN)
    assert client.post("/api/staff/admin/terms", headers=admin, json={"content": "short"}).status_code == 400
    client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG})
    again = client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG})
    assert again.status_code == 400 and "Nothing changed" in again.json()["detail"]


def test_restore_republishes_an_older_version_as_a_new_one(client, db_session):
    admin = _login(client, db_session, "admin@example.com", ROLE_ADMIN)
    v1 = client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG}).json()
    client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG + "\n\nNew clause."})
    restored = client.post(f"/api/staff/admin/terms/{v1['id']}/restore", headers=admin).json()
    assert restored["version"] == "1.3"
    assert "New clause." not in client.get("/api/payment/terms").json()["html"]


def test_preview_renders_without_publishing(client, db_session):
    admin = _login(client, db_session, "admin@example.com", ROLE_ADMIN)
    html = client.post(
        "/api/staff/admin/terms/preview", headers=admin, json={"content": "## Draft\n\nText"}
    ).json()["html"]
    assert "<h2>Draft</h2>" in html
    assert client.get("/api/payment/terms").json()["published_at"] is None


def test_only_the_admin_can_edit_the_terms(client, db_session):
    manager = _login(client, db_session, "fin@example.com", ROLE_MANAGER)
    assert client.get("/api/staff/admin/terms", headers=manager).status_code == 403
    assert client.post("/api/staff/admin/terms", headers=manager, json={"content": LONG}).status_code == 403
    assert client.post("/api/staff/admin/terms/preview", headers=manager, json={"content": "x"}).status_code == 403


def test_admin_can_open_one_published_version(client, db_session):
    admin = _login(client, db_session, "admin@example.com", ROLE_ADMIN)
    made = client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG}).json()
    one = client.get(f"/api/staff/admin/terms/{made['id']}", headers=admin).json()
    assert one["content"].startswith("## Refund Policy")
    assert "<h2>Refund Policy</h2>" in one["html"]
    assert client.get("/api/staff/admin/terms/9999", headers=admin).status_code == 404


def test_an_acceptance_records_the_version_the_customer_saw(client, db_session, seed_lead):
    from app.models.terms_acceptance import TermsAcceptance
    from tests.conftest import SAMPLE_REGISTRANT

    admin = _login(client, db_session, "admin@example.com", ROLE_ADMIN)
    client.post("/api/staff/admin/terms", headers=admin, json={"content": LONG})  # now 1.1

    seed_lead(777)
    token = client.post(
        "/api/dev/send-payment-link",
        json={"lead_id": 777, "customer_email": "x@example.com", "total_amount": "5000"},
    ).json()["token"]
    page = client.get(f"/api/payment/{token}").json()
    assert page["terms_version"] == "1.1"
    assert "Refund Policy" in page["terms_html"]

    res = client.post(
        f"/api/payment/{token}/accept", json={"accepted": True, **SAMPLE_REGISTRANT}
    )
    assert res.status_code == 200, res.text
    stored = db_session.query(TermsAcceptance).one()
    assert stored.terms_version == "1.1"
