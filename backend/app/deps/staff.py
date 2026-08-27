"""FastAPI dependencies for Cash Desk staff auth."""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.staff_user import ROLE_MANAGER, StaffUser
from app.services.staff_auth import decode_access_token

STAFF_COOKIE = "cashdesk_token"


def _token_from_request(
    authorization: str | None,
    cookie_token: str | None,
) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if cookie_token:
        return cookie_token.strip()
    return None


def get_current_staff(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    cashdesk_token: str | None = Cookie(default=None, alias=STAFF_COOKIE),
) -> StaffUser:
    token = _token_from_request(authorization, cashdesk_token)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub") or 0)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc
    user = db.get(StaffUser, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account inactive")
    return user


def require_manager(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if staff.role != ROLE_MANAGER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager only")
    return staff
