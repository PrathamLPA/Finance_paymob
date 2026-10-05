"""Google Drive uses a normal account refresh token, not a service-account key."""

from app.config import Settings
from app.integrations.google_drive import GoogleDriveClient, GoogleDriveError


def _settings(**kwargs) -> Settings:
    base = dict(
        database_url="sqlite://",
        use_mock_integrations=True,
        public_base_url="https://b2c-finance-and-ops-backend-production.up.railway.app",
        google_drive_client_id="",
        google_drive_client_secret="",
        google_drive_refresh_token="",
    )
    base.update(kwargs)
    return Settings(**base)


def test_drive_is_off_until_refresh_token_is_set():
    client = GoogleDriveClient(_settings(google_drive_client_id="id", google_drive_client_secret="sec"))
    assert client.configured is False


def test_authorization_url_asks_for_offline_drive_file_access():
    client = GoogleDriveClient(
        _settings(google_drive_client_id="client-id", google_drive_client_secret="sec")
    )
    url = client.build_authorization_url()
    assert "accounts.google.com" in url
    assert "client_id=client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "drive.file" in url
    assert url.endswith("/api/dev/google-drive/oauth-callback") or (
        "oauth-callback" in url
    )


def test_access_token_uses_refresh_grant(monkeypatch):
    captured: dict = {}

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"access_token": "ya29.token", "expires_in": 3600}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return Response()

    monkeypatch.setattr("app.integrations.google_drive.httpx.post", fake_post)
    monkeypatch.setattr(
        "app.integrations.google_drive._token_cache",
        {"token": "", "exp": 0.0, "key": ""},
    )
    client = GoogleDriveClient(
        _settings(
            google_drive_client_id="client-id",
            google_drive_client_secret="secret",
            google_drive_refresh_token="1//refresh",
        )
    )
    assert client._access_token() == "ya29.token"
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "1//refresh"


def test_exchange_requires_a_refresh_token(monkeypatch):
    class Response:
        status_code = 200
        content = b"{}"
        text = ""

        def json(self):
            return {"access_token": "short-lived"}

    monkeypatch.setattr(
        "app.integrations.google_drive.httpx.post",
        lambda url, data, timeout: Response(),
    )
    client = GoogleDriveClient(
        _settings(google_drive_client_id="client-id", google_drive_client_secret="secret")
    )
    try:
        client.exchange_authorization_code("auth-code")
    except GoogleDriveError as exc:
        assert "refresh token" in str(exc).lower()
    else:
        raise AssertionError("expected GoogleDriveError")
