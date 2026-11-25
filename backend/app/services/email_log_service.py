"""Best-effort email log. A logging failure must never stop an email or a payment."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def record_email(
    *,
    to_email: str,
    subject: str,
    body: str | None,
    status: str,
    provider_status: int | None = None,
    message_id: str | None = None,
    has_attachment: bool = False,
) -> None:
    try:
        from app.db.session import SessionLocal
        from app.models.email_log import EmailLog

        with SessionLocal() as db:
            db.add(
                EmailLog(
                    to_email=(to_email or "")[:320],
                    subject=(subject or "")[:500],
                    body=body,
                    status=status,
                    provider_status=provider_status,
                    message_id=(message_id or None) and str(message_id)[:200],
                    has_attachment=has_attachment,
                )
            )
            db.commit()
    except Exception:
        logger.warning("Could not record email log | to=%s subject=%s", to_email, subject, exc_info=True)
