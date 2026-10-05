"""Payment proof storage: local disk, or Google Drive when configured."""

from pathlib import Path
from unittest.mock import MagicMock

from app.config import Settings
from app.services.proof_storage import (
    DRIVE_PREFIX,
    person_folder_name,
    read_proof,
    store_proof,
)


def _settings(**kwargs) -> Settings:
    base = dict(
        database_url="sqlite://",
        use_mock_integrations=True,
        google_drive_client_id="",
        google_drive_client_secret="",
        google_drive_refresh_token="",
    )
    base.update(kwargs)
    return Settings(**base)


def test_store_proof_writes_local_file_when_drive_is_off(tmp_path: Path):
    stored = store_proof(
        _settings(),
        local_dir=tmp_path,
        filename="12_abc.jpg",
        content_type="image/jpeg",
        data=b"jpeg-bytes",
    )
    assert Path(stored).read_bytes() == b"jpeg-bytes"
    assert read_proof(_settings(), stored) == b"jpeg-bytes"


def test_store_proof_uses_drive_when_configured(tmp_path: Path, monkeypatch):
    drive = MagicMock()
    drive.configured = True
    drive.upload.return_value = "file-123"
    monkeypatch.setattr(
        "app.services.proof_storage.GoogleDriveClient", lambda settings: drive
    )
    stored = store_proof(
        _settings(
            google_drive_client_id="client",
            google_drive_client_secret="secret",
            google_drive_refresh_token="refresh",
        ),
        local_dir=tmp_path,
        filename="12_abc.jpg",
        person_folder="595718 - Test Customer",
        content_type="image/jpeg",
        data=b"jpeg-bytes",
    )
    assert stored == f"{DRIVE_PREFIX}file-123"
    drive.upload.assert_called_once_with(
        name="12_abc.jpg",
        mime="image/jpeg",
        data=b"jpeg-bytes",
        person_folder="595718 - Test Customer",
    )
    assert list(tmp_path.iterdir()) == []


def test_person_folder_uses_lead_id_and_name():
    assert person_folder_name(595718, "  Test   Customer ") == "595718 - Test Customer"
    assert person_folder_name(595718, None) == "595718"
    assert person_folder_name(None, "A/B") == "A B"


def test_read_proof_downloads_drive_file(monkeypatch):
    drive = MagicMock()
    drive.download.return_value = b"from-drive"
    monkeypatch.setattr(
        "app.services.proof_storage.GoogleDriveClient", lambda settings: drive
    )
    data = read_proof(_settings(), f"{DRIVE_PREFIX}file-123")
    assert data == b"from-drive"
    drive.download.assert_called_once_with("file-123")
