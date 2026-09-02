"""Cash Desk collection, deposit, employee, and ledger APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
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


@router.get("/cash/collected")
def cash_collected_list(
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    service = CashCollectionService(db)
    rows = service.list_collected(staff=staff, limit=limit)
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
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(get_current_staff),
    proof: UploadFile = File(...),
    amount: str | None = Form(default=None),
) -> dict[str, Any]:
    from app.models.cash_collection import CashCollection

    service = CashCollectionService(db)
    row = db.get(CashCollection, collection_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cash collection not found")

    data = await proof.read()
    try:
        service.save_proof(
            row,
            filename=proof.filename or "cash-proof.jpg",
            content_type=proof.content_type,
            data=data,
            staff=staff,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chosen: Decimal | None = None
    if amount and str(amount).strip():
        try:
            chosen = Decimal(str(amount).strip())
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid amount") from exc

    orchestrator = WorkflowOrchestrator(db)
    try:
        workflow = await orchestrator.collect_cash(
            collection_id, staff_id=staff.id, amount=chosen
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@router.get("/cash/{collection_id}/proof")
def cash_collection_proof(
    collection_id: int,
    db: Session = Depends(get_db),
    _staff: StaffUser = Depends(get_current_staff),
):
    from fastapi.responses import Response

    from app.models.cash_collection import CashCollection

    row = db.get(CashCollection, collection_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cash collection not found")
    try:
        data, ctype, name = CashCollectionService(db).read_proof_bytes(row)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=ctype,
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


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


class InvoiceRetriggerBody(BaseModel):
    payment_transaction_id: int | None = None
    transaction_id: str | None = None
    workflow_id: int | None = None
    lead_id: int | None = None


@router.post("/invoices/retrigger")
async def retrigger_invoice(
    body: InvoiceRetriggerBody,
    db: Session = Depends(get_db),
    _manager: StaffUser = Depends(require_manager),
) -> dict[str, Any]:
    """Create missing Zoho invoice and (re)send to Bitrix + customer email."""
    from sqlalchemy import select

    from app.models.customer_workflow import CustomerWorkflow
    from app.models.payment_transaction import PaymentTransaction
    from app.services.invoice_service import InvoiceService

    txn: PaymentTransaction | None = None
    if body.payment_transaction_id is not None:
        txn = db.get(PaymentTransaction, body.payment_transaction_id)
    elif body.transaction_id:
        txn = db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.transaction_id == body.transaction_id
            )
        )

    workflow: CustomerWorkflow | None = None
    if txn is not None:
        workflow = txn.workflow
    elif body.workflow_id is not None:
        workflow = db.get(CustomerWorkflow, body.workflow_id)
    elif body.lead_id is not None:
        workflow = db.scalar(
            select(CustomerWorkflow).where(CustomerWorkflow.bitrix_lead_id == body.lead_id)
        )

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found for this payment")

    if txn is None:
        txn = db.scalar(
            select(PaymentTransaction)
            .where(PaymentTransaction.workflow_id == workflow.id)
            .order_by(PaymentTransaction.paid_at.desc())
        )
    if txn is None:
        raise HTTPException(
            status_code=400,
            detail="No recorded payment found for this workflow - cannot create invoice",
        )

    result = await InvoiceService(db).retrigger_invoice_delivery(workflow, txn)
    if not result.get("ok") and str(result.get("steps", {}).get("zoho", "")).startswith(
        "error"
    ):
        raise HTTPException(
            status_code=400,
            detail=result.get("detail") or "Invoice retrigger failed in Zoho",
        )
    return result
