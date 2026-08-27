"""Cash Desk staff authentication APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps.staff import STAFF_COOKIE, get_current_staff
from app.models.staff_user import StaffUser
from app.services.staff_auth import authenticate_staff, create_access_token

router = APIRouter(prefix="/api/staff", tags=["staff"])


class LoginBody(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


def _user_public(user: StaffUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.post("/login")
def staff_login(body: LoginBody, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = authenticate_staff(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user)
    settings = get_settings()
    response.set_cookie(
        key=STAFF_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env.lower() == "production",
        max_age=max(1, settings.staff_jwt_ttl_hours) * 3600,
        path="/",
    )
    return {"token": token, "user": _user_public(user)}


@router.post("/logout")
def staff_logout(response: Response) -> dict[str, str]:
    response.delete_cookie(STAFF_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def staff_me(staff: StaffUser = Depends(get_current_staff)) -> dict[str, Any]:
    return _user_public(staff)
