"""Shared customer email checks for Bitrix sync and payment flows."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str | None) -> bool:
    """Return True when value looks like a usable billing/contact email."""
    if value in (None, ""):
        return False
    email = str(value).strip()
    if not email or len(email) > 254 or " " in email:
        return False
    return bool(_EMAIL_RE.match(email))


def invalid_email_comment(email: str | None) -> str:
    """Bitrix timeline message when an address cannot be used."""
    display = (email or "").strip() or "(empty)"
    return f"{display} is not a valid mail"
