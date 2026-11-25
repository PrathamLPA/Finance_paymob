"""Developer administrator: people, live counts, and the finance-verification switch."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.staff import require_admin, require_manager, scope_to_data_mode
from app.models.bank_transfer import BankTransferSubmission
from app.models.cash_collection import STATUS_CLAIMED, STATUS_OPEN, CashCollection
from app.config import get_settings
from app.db.data_mode import MODE_LIVE, current_data_mode, set_data_mode
from app.services.data_reset import clear_mode_data
from app.models.customer_workflow import CustomerWorkflow
from app.models.email_log import EmailLog
from app.models.finance_verification import STATUS_PENDING, FinanceVerification
from app.models.payment_session import PaymentSession
from app.models.price_approval import PriceApproval
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_MANAGER, StaffUser
from app.services.finance_verification_service import FinanceVerificationService
from app.services.staff_auth import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/staff/admin", tags=["admin"], dependencies=[Depends(scope_to_data_mode)]
)

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


class DataModeBody(BaseModel):
    mode: Literal["test", "live"]


class ClearDataBody(BaseModel):
    confirm: str = ""


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
        "data_mode": current_data_mode(),
    }


@router.put("/data-mode")
def set_mode(
    body: DataModeBody,
    db: Session = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    mode = set_data_mode(db, body.mode, admin.id)
    logger.warning("Data mode set to %s by %s", mode, admin.email)
    return {"data_mode": mode}


@router.post("/clear-data")
def clear_data(
    body: ClearDataBody,
    db: Session = Depends(get_db),
    admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    """Delete every payment record of the ACTIVE mode only (the other mode is untouched)."""
    mode = current_data_mode()
    phrase = "DELETE LIVE DATA" if mode == MODE_LIVE else "CLEAR TEST DATA"
    if body.confirm.strip() != phrase:
        raise HTTPException(status_code=400, detail=f"Type {phrase} to confirm")
    logger.warning("Clearing %s payment data | requested by %s", mode, admin.email)
    deleted = clear_mode_data(db, mode)
    return {"data_mode": mode, "deleted": deleted}


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


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("/payment-links")
def payment_links_overview(
    limit: int = 200,
    db: Session = Depends(get_db),
    _admin: StaffUser = Depends(require_admin),
) -> dict[str, Any]:
    """Every payment link, the emails sent, the mode chosen and what still needs approval."""
    limit = max(1, min(limit, 500))
    settings = get_settings()
    base = (settings.payment_frontend_base_url or settings.public_base_url or "").rstrip("/")

    emails = list(
        db.scalars(select(EmailLog).order_by(EmailLog.id.desc()).limit(500)).all()
    )
    rows = db.execute(
        select(PaymentSession, CustomerWorkflow)
        .join(CustomerWorkflow, CustomerWorkflow.id == PaymentSession.workflow_id)
        .order_by(PaymentSession.id.desc())
        .limit(limit)
    ).all()

    session_ids = [session.id for session, _ in rows]
    txn_by_session: dict[int, PaymentTransaction] = {}
    verification_by_txn: dict[int, FinanceVerification] = {}
    if session_ids:
        for txn in db.scalars(
            select(PaymentTransaction).where(PaymentTransaction.payment_session_id.in_(session_ids))
        ):
            if txn.payment_session_id is not None:
                txn_by_session[txn.payment_session_id] = txn
        txn_ids = [t.id for t in txn_by_session.values()]
        if txn_ids:
            for ver in db.scalars(
                select(FinanceVerification).where(
                    FinanceVerification.payment_transaction_id.in_(txn_ids)
                )
            ):
                verification_by_txn[ver.payment_transaction_id] = ver

    def _emails_for(token: str) -> list[dict[str, Any]]:
        return [
            {
                "id": mail.id,
                "to": mail.to_email,
                "subject": mail.subject,
                "status": mail.status,
                "sent_at": _iso(mail.created_at),
            }
            for mail in emails
            if token and token in (mail.body or "")
        ]

    links: list[dict[str, Any]] = []
    for session, workflow in rows:
        txn = txn_by_session.get(session.id)
        ver = verification_by_txn.get(txn.id) if txn is not None else None
        links.append(
            {
                "id": session.id,
                "lead_id": workflow.bitrix_lead_id,
                "customer_name": workflow.customer_name,
                "customer_email": workflow.customer_email,
                "customer_phone": workflow.customer_phone,
                "bitrix_posted_at": _iso(session.link_commented_at),
                "amount": str(session.charge_amount),
                "currency": session.currency,
                "installment_number": session.installment_number,
                "channel": session.channel,
                "chosen_mode": session.customer_payment_mode,
                "paid_with": txn.source_type if txn is not None else None,
                "status": session.status,
                "payment_url": f"{base}/payment/{session.token}",
                "paymob_checkout_url": session.paymob_checkout_url,
                "created_at": _iso(session.created_at),
                "expires_at": _iso(session.expires_at),
                "completed_at": _iso(session.completed_at),
                "emails": _emails_for(session.token),
                "approval": (
                    {"id": ver.id, "status": ver.status} if ver is not None else None
                ),
            }
        )

    pending: list[dict[str, Any]] = []
    for ver in db.scalars(
        select(FinanceVerification)
        .where(FinanceVerification.status == STATUS_PENDING)
        .order_by(FinanceVerification.id.desc())
    ):
        txn = db.get(PaymentTransaction, ver.payment_transaction_id)
        session = (
            db.get(PaymentSession, txn.payment_session_id)
            if txn is not None and txn.payment_session_id
            else None
        )
        pending.append(
            {
                "id": ver.id,
                "lead_id": ver.bitrix_lead_id,
                "customer_name": ver.customer_name,
                "amount": ver.amount,
                "currency": ver.currency,
                "channel": ver.channel,
                "chosen_mode": session.customer_payment_mode if session is not None else None,
                "paid_with": txn.source_type if txn is not None else None,
                "transaction_id": txn.transaction_id if txn is not None else None,
                "created_at": _iso(ver.created_at),
            }
        )

    def _naive(value: Any) -> Any:
        return value.replace(tzinfo=None) if value is not None else None

    def _link_after(approval: PriceApproval, workflow: CustomerWorkflow) -> dict[str, Any] | None:
        """The payment link created for this lead once the manager approved."""
        if approval.status != "approved" or approval.decided_at is None:
            return None
        decided = _naive(approval.decided_at)
        for session in db.scalars(
            select(PaymentSession)
            .where(PaymentSession.workflow_id == workflow.id)
            .order_by(PaymentSession.id.desc())
            .limit(5)
        ):
            if _naive(session.created_at) is not None and _naive(session.created_at) >= decided:
                return {
                    "url": f"{base}/payment/{session.token}",
                    "status": session.status,
                    "created_at": _iso(session.created_at),
                    "bitrix_posted_at": _iso(session.link_commented_at),
                    "emails": _emails_for(session.token),
                }
        return None

    approvals: list[dict[str, Any]] = []
    for approval, workflow in db.execute(
        select(PriceApproval, CustomerWorkflow)
        .join(CustomerWorkflow, CustomerWorkflow.id == PriceApproval.workflow_id)
        .order_by(PriceApproval.id.desc())
        .limit(limit)
    ).all():
        approvals.append(
            {
                "id": approval.id,
                "lead_id": approval.bitrix_lead_id,
                "lead_title": approval.lead_title,
                "customer_name": workflow.customer_name,
                "sales_owner": approval.owner_name,
                "manager_name": approval.manager_name,
                "manager_email": approval.manager_email,
                "status": approval.status,
                "reason": approval.reason,
                "currency": approval.currency,
                "total_payable": approval.total_payable,
                "catalog_minimum_total": approval.catalog_minimum_total,
                "sent_at": _iso(approval.notified_at),
                "sent_via": approval.notified_via,
                "created_at": _iso(approval.created_at),
                "expires_at": _iso(approval.expires_at),
                "decided_at": _iso(approval.decided_at),
                "decision_note": approval.decision_note,
                "approval_url": f"{base}/approvals/{approval.token}",
                "emails": _emails_for(approval.token),
                "customer_email": workflow.customer_email,
                "customer_phone": workflow.customer_phone,
                "payment_link": _link_after(approval, workflow),
            }
        )

    return {
        "verification_enabled": FinanceVerificationService(db).is_enabled(),
        "price_approvals": approvals,
        "links": links,
        "pending_approvals": pending,
        "emails": [
            {
                "id": mail.id,
                "to": mail.to_email,
                "subject": mail.subject,
                "status": mail.status,
                "has_attachment": mail.has_attachment,
                "sent_at": _iso(mail.created_at),
                "body": mail.body,
            }
            for mail in emails[:limit]
        ],
    }
