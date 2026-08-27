"""Password hashing and JWT helpers for Cash Desk staff."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.staff_user import ROLE_MANAGER, StaffUser

_PBKDF2_ROUNDS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, rounds_s, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_s)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds
    ).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(user: StaffUser, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    secret = (settings.staff_jwt_secret or "").strip()
    if not secret:
        raise RuntimeError("STAFF_JWT_SECRET is not configured")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=max(1, settings.staff_jwt_ttl_hours)),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    secret = (settings.staff_jwt_secret or "").strip()
    if not secret:
        raise RuntimeError("STAFF_JWT_SECRET is not configured")
    return jwt.decode(token, secret, algorithms=["HS256"])


def authenticate_staff(db: Session, email: str, password: str) -> StaffUser | None:
    user = db.scalar(select(StaffUser).where(StaffUser.email == email.strip().lower()))
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def sync_bootstrap_manager_credentials(db: Session, settings: Settings | None = None) -> StaffUser | None:
    """Ensure bootstrap manager exists and password matches env (safe for redeploy password reset)."""
    settings = settings or get_settings()
    email = (settings.staff_bootstrap_manager_email or "").strip().lower()
    password = settings.staff_bootstrap_manager_password or ""
    name = (settings.staff_bootstrap_manager_name or "Cash Desk Manager").strip()
    if not email or not password:
        return None

    user = db.scalar(select(StaffUser).where(StaffUser.email == email))
    if user:
        user.role = ROLE_MANAGER
        user.is_active = True
        user.password_hash = hash_password(password)
        if name:
            user.name = name
        db.commit()
        db.refresh(user)
        return user

    user = StaffUser(
        email=email,
        name=name,
        password_hash=hash_password(password),
        role=ROLE_MANAGER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def bootstrap_manager_if_needed(db: Session, settings: Settings | None = None) -> StaffUser | None:
    """Create or refresh the bootstrap manager from env."""
    return sync_bootstrap_manager_credentials(db, settings)
