"""Cash Desk collection, deposit, employee, and ledger APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.staff import get_current_staff, require_manager
from app.models.staff_user import ROLE_MANAGER, StaffUser
from app.services.cash_collection_service import CashCollectionService
from app.services.workflow_orchestrator import WorkflowOrchestrator

router = APIRouter(prefix="/api/staff", tags=["cash-desk"])


class EmployeeCreateBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=6)


class EmployeePatchBody(BaseModel):
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6)
    name: str | None = Field(default=None, min_length=1, max_length=255)


class CollectBody(BaseModel):
    amount: Decimal | None = None


class DepositBody(BaseModel):
    amount: Decimal
    note: str | None = None
    employee_id: int | None = None


class BankTransferReviewBody(BaseModel):
    note: str | None = None
    amount: Decimal | None = None


@router.get("/cash/queue")
def cash_queue(
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
) -> dict[str, Any]:
    service = CashCollectionService(db)
    rows = service.list_queue(staff=staff)
    return {"items": [service.collection_to_dict(r) for r in rows]}


@router.post("/cash/{collection_id}/claim")
def cash_claim(
    collection_id: int,
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
) -> dict[str, Any]:
    service = CashCollectionService(db)
    try:
        row = service.claim(collection_id, staff)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.collection_to_dict(row)


@router.post("/cash/{collection_id}/collect")
async def cash_collect(
    collection_id: int,
    body: CollectBody,
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
) -> dict[str, Any]:
    orchestrator = WorkflowOrchestrator(db)
    try:
        workflow = await orchestrator.collect_cash(
            collection_id, staff_id=staff.id, amount=body.amount
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service = CashCollectionService(db)
    from app.models.cash_collection import CashCollection

    row = db.get(CashCollection, collection_id)
    return {
        "collection": service.collection_to_dict(row) if row else None,
        "workflow": {
            "id": workflow.id,
            "amount_paid": str(workflow.amount_paid),
            "remaining_balance": str(workflow.remaining_balance),
            "payment_status": workflow.payment_status,
        },
    }


@router.get("/cash/my-summary")
def cash_my_summary(
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
) -> dict[str, Any]:
    service = CashCollectionService(db)
    bal = service.employee_balances(staff.id)
    return {
        "employee_id": staff.id,
        "on_hand": str(bal["on_hand"]),
        "deposited": str(bal["deposited"]),
        "left_to_deposit": str(bal["left_to_deposit"]),
        "collected": str(bal["collected"]),
        "currency": "AED",
    }


@router.post("/cash/deposits")
def cash_deposit(
    body: DepositBody,
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
) -> dict[str, Any]:
    service = CashCollectionService(db)
    employee_id = body.employee_id or staff.id
    try:
        row = service.record_deposit(
            employee_id=employee_id,
            amount=body.amount,
            note=body.note,
            recorded_by=staff,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    bal = service.employee_balances(employee_id)
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "amount": str(row.amount),
        "note": row.note,
        "deposited_at": row.deposited_at.isoformat() if row.deposited_at else None,
        "balances": {
            "on_hand": str(bal["on_hand"]),
            "deposited": str(bal["deposited"]),
            "left_to_deposit": str(bal["left_to_deposit"]),
        },
    }


@router.get("/cash/deposits")
def cash_deposits_list(
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
) -> dict[str, Any]:
    service = CashCollectionService(db)
    if staff.role != ROLE_MANAGER:
        employee_id = staff.id
    rows = service.list_deposits(employee_id=employee_id)
    return {
        "items": [
            {
                "id": r.id,
                "employee_id": r.employee_id,
                "employee_name": r.employee.name if r.employee else None,
                "amount": str(r.amount),
                "currency": r.currency,
                "note": r.note,
                "deposited_at": r.deposited_at.isoformat() if r.deposited_at else None,
                "recorded_by_name": r.recorded_by.name if r.recorded_by else None,
            }
            for r in rows
        ]
    }


@router.get("/employees")
def list_employees(
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    return {"items": CashCollectionService(db).list_employees()}


@router.post("/employees")
def create_employee(
    body: EmployeeCreateBody,
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    try:
        user = CashCollectionService(db).create_employee(
            email=body.email, name=body.name, password=body.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


@router.patch("/employees/{employee_id}")
def patch_employee(
    employee_id: int,
    body: EmployeePatchBody,
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    try:
        user = CashCollectionService(db).patch_employee(
            employee_id,
            is_active=body.is_active,
            password=body.password,
            name=body.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_active": user.is_active,
        "role": user.role,
    }


@router.get("/dashboard")
def manager_dashboard(
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    return CashCollectionService(db).dashboard()


@router.get("/transactions")
def manager_transactions(
    channel: Literal["all", "cash", "online"] = Query(default="all"),
    employee_id: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    items = CashCollectionService(db).list_transactions(
        channel=channel, employee_id=employee_id, q=q
    )
    return {"items": items}


@router.get("/bank-transfers")
def bank_transfers_list(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    from app.services.bank_transfer_service import BankTransferService

    service = BankTransferService(db)
    rows = service.list_for_manager(status=status)
    return {"items": [service.submission_to_dict(r) for r in rows]}


@router.get("/bank-transfers/{submission_id}")
def bank_transfer_detail(
    submission_id: int,
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    from app.models.bank_transfer import BankTransferSubmission
    from app.services.bank_transfer_service import BankTransferService

    service = BankTransferService(db)
    row = db.get(BankTransferSubmission, submission_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bank transfer not found")
    return service.submission_to_dict(row)


@router.get("/bank-transfers/{submission_id}/proof")
def bank_transfer_proof(
    submission_id: int,
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
):
    from fastapi.responses import Response

    from app.models.bank_transfer import BankTransferSubmission
    from app.services.bank_transfer_service import BankTransferService

    row = db.get(BankTransferSubmission, submission_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bank transfer not found")
    try:
        data, ctype, name = BankTransferService(db).read_proof_bytes(row)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=ctype,
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


@router.post("/bank-transfers/{submission_id}/approve")
async def bank_transfer_approve(
    submission_id: int,
    body: BankTransferReviewBody,
    db: Session = Depends(get_db),
    manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    from app.services.bank_transfer_service import BankTransferService

    service = BankTransferService(db)
    try:
        row = await service.approve(
            submission_id, staff=manager, note=body.note, amount=body.amount
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.submission_to_dict(row)


@router.post("/bank-transfers/{submission_id}/reject")
async def bank_transfer_reject(
    submission_id: int,
    body: BankTransferReviewBody,
    db: Session = Depends(get_db),
    manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    from app.services.bank_transfer_service import BankTransferService

    service = BankTransferService(db)
    try:
        row = await service.reject(submission_id, staff=manager, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return service.submission_to_dict(row)
