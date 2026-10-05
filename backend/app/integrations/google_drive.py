"""Google Drive storage for payment proof images and PDFs.

A normal Google account signs in once (OAuth refresh token). Photos are
stored in that account's Drive under a folder named ``fynx``. Inside that,
each customer gets a folder (lead id and name). Both folders are created
when they do not already exist. Files stay private; the finance UI loads
them through our API.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
# Files the app creates only. This scope does not need a Google security review.
_SCOPE = "https://www.googleapis.com/auth/drive.file"
_FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = "fynx"
OAUTH_CALLBACK_PATH = "/api/dev/google-drive/oauth-callback"
_token_cache: dict[str, Any] = {"token": "", "exp": 0.0, "key": ""}
_folder_cache: dict[tuple[str, str], str] = {}


class GoogleDriveError(RuntimeError):
    pass


class GoogleDriveClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(
            self._client_id() and self._client_secret() and self._refresh_token()
        )

    def _client_id(self) -> str:
        return (self.settings.google_drive_client_id or "").strip()

    def _client_secret(self) -> str:
        return (self.settings.google_drive_client_secret or "").strip()

    def _refresh_token(self) -> str:
        return (self.settings.google_drive_refresh_token or "").strip()

    def redirect_uri(self) -> str:
        explicit = (self.settings.google_drive_redirect_uri or "").strip()
        if explicit:
            return explicit
        base = (self.settings.public_base_url or "").strip().rstrip("/")
        if not base:
            raise GoogleDriveError("PUBLIC_BASE_URL is required for the Google sign-in redirect")
        return f"{base}{OAUTH_CALLBACK_PATH}"

    def build_authorization_url(self) -> str:
        if not self._client_id():
            raise GoogleDriveError("GOOGLE_DRIVE_CLIENT_ID is required")
        params = {
            "client_id": self._client_id(),
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_authorization_code(self, code: str) -> dict[str, Any]:
        """Trade the one-time Google code for a refresh token to store in Railway."""
        if not self._client_id() or not self._client_secret():
            raise GoogleDriveError(
                "GOOGLE_DRIVE_CLIENT_ID and GOOGLE_DRIVE_CLIENT_SECRET are required"
            )
        grant = (code or "").strip()
        if not grant:
            raise GoogleDriveError("Google did not return a sign-in code")
        response = httpx.post(
            _TOKEN_URL,
            data={
                "code": grant,
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "redirect_uri": self.redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=30.0,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400 or data.get("error"):
            raise GoogleDriveError(self._token_error("Google sign-in", response, data))
        refresh = str(data.get("refresh_token") or "").strip()
        if not refresh:
            raise GoogleDriveError(
                "Google did not return a refresh token. Open the connect link again "
                "and approve access. If this Google account already approved the app, "
                "remove Finance Paymob from https://myaccount.google.com/permissions and retry."
            )
        return {
            "refresh_token": refresh,
            "expires_in": data.get("expires_in"),
            "scope": data.get("scope"),
        }

    def _access_token(self) -> str:
        refresh = self._refresh_token()
        if not self._client_id() or not self._client_secret() or not refresh:
            raise GoogleDriveError(
                "Google Drive is not configured. Set GOOGLE_DRIVE_CLIENT_ID, "
                "GOOGLE_DRIVE_CLIENT_SECRET, and GOOGLE_DRIVE_REFRESH_TOKEN."
            )
        cache_key = f"{self._client_id()}:{refresh[:12]}"
        now = time.time()
        if (
            _token_cache["token"]
            and _token_cache["key"] == cache_key
            and float(_token_cache["exp"]) > now + 60
        ):
            return str(_token_cache["token"])
        response = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=30.0,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400 or data.get("error"):
            raise GoogleDriveError(self._token_error("Google Drive auth", response, data))
        token = str(data.get("access_token") or "")
        if not token:
            raise GoogleDriveError("Google Drive auth returned no access token")
        _token_cache["token"] = token
        _token_cache["key"] = cache_key
        _token_cache["exp"] = now + 3500
        return token

    def account_email(self) -> str:
        """Email of the Google account that owns the Drive folders."""
        response = httpx.get(
            _ABOUT_URL,
            params={"fields": "user(emailAddress)"},
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise GoogleDriveError(
                f"Google Drive account check failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        user = response.json().get("user") or {}
        return str(user.get("emailAddress") or "")

    def ensure_folder(self, name: str, parent_id: str = "root") -> str:
        """Return the id of a folder with this name under parent, creating it if needed."""
        key = (parent_id, name)
        cached = _folder_cache.get(key)
        if cached:
            return cached
        found = self._find_folder(name, parent_id)
        folder_id = found or self._create_folder(name, parent_id)
        _folder_cache[key] = folder_id
        return folder_id

    def _find_folder(self, name: str, parent_id: str) -> str | None:
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"name = '{safe}' and mimeType = '{_FOLDER_MIME}' "
            f"and trashed = false and '{parent_id}' in parents"
        )
        response = httpx.get(
            _FILES_URL,
            params={
                "q": query,
                "fields": "files(id,name)",
                "pageSize": 1,
                "supportsAllDrives": "true",
            },
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise GoogleDriveError(
                f"Google Drive folder search failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        files = response.json().get("files") or []
        if not files:
            return None
        return str(files[0].get("id") or "").strip() or None

    def _create_folder(self, name: str, parent_id: str) -> str:
        response = httpx.post(
            _FILES_URL,
            params={"supportsAllDrives": "true"},
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
            json={
                "name": name,
                "mimeType": _FOLDER_MIME,
                "parents": [parent_id],
            },
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise GoogleDriveError(
                f"Google Drive folder create failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        folder_id = str(response.json().get("id") or "").strip()
        if not folder_id:
            raise GoogleDriveError(f"Google Drive did not return an id for folder {name}")
        logger.info(
            "Created Google Drive folder | name=%s parent=%s id=%s",
            name,
            parent_id,
            folder_id,
        )
        return folder_id

    def upload(
        self,
        *,
        name: str,
        mime: str,
        data: bytes,
        person_folder: str,
    ) -> str:
        root_id = self.ensure_folder(ROOT_FOLDER_NAME, "root")
        person_id = self.ensure_folder(person_folder, root_id)
        boundary = "finance_paymob_drive"
        metadata = json.dumps({"name": name, "parents": [person_id]})
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--".encode("utf-8")
        response = httpx.post(
            _UPLOAD_URL,
            params={"uploadType": "multipart", "supportsAllDrives": "true"},
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body,
            timeout=60.0,
        )
        if response.status_code >= 400:
            raise GoogleDriveError(
                f"Google Drive upload failed ({response.status_code}): {response.text[:400]}"
            )
        file_id = str(response.json().get("id") or "").strip()
        if not file_id:
            raise GoogleDriveError("Google Drive upload returned no file id")
        logger.info("Uploaded proof to Google Drive | name=%s file_id=%s", name, file_id)
        return file_id

    def download(self, file_id: str) -> bytes:
        response = httpx.get(
            f"{_FILES_URL}/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=60.0,
        )
        if response.status_code >= 400:
            raise GoogleDriveError(
                f"Google Drive download failed ({response.status_code}): {response.text[:300]}"
            )
        return response.content

    def delete(self, file_id: str) -> None:
        response = httpx.delete(
            f"{_FILES_URL}/{file_id}",
            params={"supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=30.0,
        )
        if response.status_code in (200, 204, 404):
            return
        logger.warning(
            "Could not delete Google Drive file %s status=%s",
            file_id,
            response.status_code,
        )

    @staticmethod
    def _token_error(label: str, response: httpx.Response, data: dict[str, Any]) -> str:
        code = str(data.get("error") or "")
        detail = str(data.get("error_description") or response.text[:300])
        hint = ""
        if code == "invalid_grant":
            hint = (
                " Sign in again from /api/dev/google-drive/connect. "
                "A refresh token from an unpublished test app expires after 7 days."
            )
        return f"{label} failed ({response.status_code}): {detail}{hint}"
