"""Manager price-approval APIs consumed by the frontend approval page."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.cash_collection_service import CashCollectionQueued
from app.services.price_approval_service import PriceApprovalService
from app.services.workflow_orchestrator import WorkflowOrchestrator

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ProductPriceOverride(BaseModel):
    product_id: int
    selling_price: Decimal


class InstallmentOverride(BaseModel):
    number: int
    amount: Decimal | None = None
    due_date: str | None = None


class DecisionBody(BaseModel):
    note: str | None = None
    product_prices: list[ProductPriceOverride] = Field(default_factory=list)
    installments: list[InstallmentOverride] = Field(default_factory=list)
    rejected_case: str | None = None


@router.get("/{token}")
async def get_approval(token: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    service = PriceApprovalService(db)
    approval = service.get_by_token(token)
    if not approval:
        raise HTTPException(status_code=404, detail="This approval link is invalid or has expired.")
    return service.to_public_dict(approval)


@router.post("/{token}/approve")
async def approve_price(token: str, body: DecisionBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    orchestrator = WorkflowOrchestrator(db)
    try:
        session = await orchestrator.complete_approved_payment(
            token,
            note=body.note,
            product_prices=[p.model_dump() for p in body.product_prices],
            installment_overrides=[i.model_dump() for i in body.installments],
        )
    except CashCollectionQueued as exc:
        collection = exc.collection
        return {
            "status": "approved",
            "cash_queued": True,
            "collection_id": collection.id,
            "installment_number": collection.installment_number,
            "due_amount": str(collection.due_amount),
            "currency": collection.currency,
            "lead_id": collection.bitrix_lead_id,
            "payment_url": None,
            "message": (
                "Payment mode is Cash - no Paymob link was sent. "
                "Collect cash in Cash Desk."
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payment_url = orchestrator.session_service.build_payment_url(session.token)
    return {
        "status": "approved",
        "cash_queued": False,
        "payment_url": payment_url,
        "lead_id": session.source_id if session.source_type == "lead" else None,
        "workflow_id": session.workflow_id,
    }


@router.post("/{token}/reject")
async def reject_price(token: str, body: DecisionBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    orchestrator = WorkflowOrchestrator(db)
    try:
        await orchestrator.reject_price_approval(
            token,
            note=body.note,
            product_prices=[p.model_dump() for p in body.product_prices],
            installment_overrides=[i.model_dump() for i in body.installments],
            rejected_case=body.rejected_case,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "rejected"}
