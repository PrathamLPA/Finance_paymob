"""Save payment proofs on Google Drive when configured, otherwise on local disk."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.integrations.google_drive import GoogleDriveClient, GoogleDriveError

logger = logging.getLogger(__name__)

DRIVE_PREFIX = "gdrive:"


def person_folder_name(lead_id: int | None, customer_name: str | None) -> str:
    """Drive folder under fynx: lead id plus customer name."""
    name = " ".join((customer_name or "").split())
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, " ")
    name = " ".join(name.split()).strip()[:80]
    if lead_id and name:
        return f"{lead_id} - {name}"
    if lead_id:
        return str(lead_id)
    return name or "unknown"


def store_proof(
    settings: Settings,
    *,
    local_dir: Path,
    filename: str,
    content_type: str,
    data: bytes,
    person_folder: str | None = None,
) -> str:
    """Return the value to store in proof_path."""
    drive = GoogleDriveClient(settings)
    if drive.configured:
        file_id = drive.upload(
            name=filename,
            mime=content_type,
            data=data,
            person_folder=person_folder or "unknown",
        )
        return f"{DRIVE_PREFIX}{file_id}"
    local_dir.mkdir(parents=True, exist_ok=True)
    dest = local_dir / filename
    dest.write_bytes(data)
    return str(dest)


def read_proof(settings: Settings, stored: str) -> bytes:
    if stored.startswith(DRIVE_PREFIX):
        file_id = stored[len(DRIVE_PREFIX) :].strip()
        if not file_id:
            raise ValueError("Proof file id is missing")
        try:
            return GoogleDriveClient(settings).download(file_id)
        except GoogleDriveError as exc:
            raise ValueError(str(exc)) from exc
    path = Path(stored)
    if not path.is_file():
        raise ValueError("Proof file missing on disk")
    return path.read_bytes()


def delete_proof(settings: Settings, stored: str | None, *, local_dir: Path) -> None:
    if not stored:
        return
    if stored.startswith(DRIVE_PREFIX):
        file_id = stored[len(DRIVE_PREFIX) :].strip()
        if not file_id:
            return
        try:
            GoogleDriveClient(settings).delete(file_id)
        except GoogleDriveError:
            logger.exception("Could not delete Google Drive proof %s", file_id)
        return
    try:
        old = Path(stored)
        if old.is_file() and old.resolve().parent == local_dir.resolve():
            old.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove old proof %s", stored)
