"""Developer administrator: people, live counts, and the finance-verification switch."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.staff import require_admin, require_manager
from app.models.bank_transfer import BankTransferSubmission
from app.models.cash_collection import STATUS_CLAIMED, STATUS_OPEN, CashCollection
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_MANAGER, StaffUser
from app.services.finance_verification_service import FinanceVerificationService
from app.services.staff_auth import hash_password

router = APIRouter(prefix="/api/staff/admin", tags=["admin"])

_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_EMPLOYEE}


class StaffCreateBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=6)
    role: Literal["admin", "manager", "employee"] = "employee"


class StaffPatchBody(BaseModel):
    is_active: bool | None = None
    role: Literal["admin", "manager", "employee"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=6)


class VerificationToggleBody(BaseModel):
    enabled: bool


class VerificationDecisionBody(BaseModel):
    note: str | None = None


def _person(user: StaffUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.get("/overview")
def admin_overview(
    db: Session = Depends(get_db),
    _admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    service = FinanceVerificationService(db)
    staff = service.staff_counts()
    txn_count = db.scalar(select(func.count()).select_from(PaymentTransaction)) or 0
    open_cash = db.scalar(
        select(func.count())
        .select_from(CashCollection)
        .where(CashCollection.status.in_([STATUS_OPEN, STATUS_CLAIMED]))
    ) or 0
    pending_bank = db.scalar(
        select(func.count())
        .select_from(BankTransferSubmission)
        .where(BankTransferSubmission.status == "pending_review")
    ) or 0
    return {
        "finance_manager_verification": service.is_enabled(),
        "staff": staff,
        "staff_total": sum(staff.values()),
        "transactions": int(txn_count),
        "open_cash_collections": int(open_cash),
        "pending_bank_transfers": int(pending_bank),
        "pending_verifications": service.counts()["pending"],
    }


@router.put("/verification")
def set_verification(
    body: VerificationToggleBody,
    db: Session = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    enabled = FinanceVerificationService(db).set_enabled(body.enabled, admin)
    return {"finance_manager_verification": enabled}


@router.get("/people")
def list_people(
    db: Session = Depends(get_db),
    _admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    users = list(db.scalars(select(StaffUser).order_by(StaffUser.role, StaffUser.name)).all())
    return {"items": [_person(u) for u in users]}


@router.post("/people")
def create_person(
    body: StaffCreateBody,
    db: Session = Depends(get_db),
    _admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    email = body.email.strip().lower()
    if body.role not in _ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    existing = db.scalar(select(StaffUser).where(StaffUser.email == email))
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    user = StaffUser(
        email=email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _person(user)


@router.patch("/people/{user_id}")
def patch_person(
    user_id: int,
    body: StaffPatchBody,
    db: Session = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    user = db.get(StaffUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if user.id == admin.id and body.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    if user.id == admin.id and body.role and body.role != ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="You cannot remove your own administrator role")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.name is not None and body.name.strip():
        user.name = body.name.strip()
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return _person(user)


@router.get("/verifications")
def list_verifications(
    status: str | None = None,
    db: Session = Depends(get_db),
    _reviewer: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    service = FinanceVerificationService(db)
    return {
        "enabled": service.is_enabled(),
        "items": service.list_items(status=status),
    }


@router.post("/verifications/{verification_id}/approve")
async def approve_verification(
    verification_id: int,
    body: VerificationDecisionBody,
    db: Session = Depends(get_db),
    reviewer: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    try:
        return await FinanceVerificationService(db).decide(
            verification_id, staff=reviewer, approve=True, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/verifications/{verification_id}/reject")
async def reject_verification(
    verification_id: int,
    body: VerificationDecisionBody,
    db: Session = Depends(get_db),
    reviewer: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    try:
        return await FinanceVerificationService(db).decide(
            verification_id, staff=reviewer, approve=False, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
