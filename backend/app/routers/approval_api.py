"""Manager price-approval APIs consumed by the frontend approval page."""

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.cash_collection_service import CashCollectionQueued
from app.services.price_approval_service import PriceApprovalService
from app.services.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ProductPriceOverride(BaseModel):
    product_id: int
    # Identifies custom/unlinked course rows where Bitrix product_id is 0.
    line_index: int | None = None
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


def _check_can_decide(service: PriceApprovalService, token: str):
    """Answer invalid / already-decided / expired links straight away."""
    from datetime import datetime, timezone

    approval = service.get_by_token(token)
    if not approval:
        raise ValueError("This approval link is invalid.")
    if approval.status != "pending":
        raise ValueError(f"This request was already {approval.status}.")
    expires = approval.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise ValueError("This approval link has expired.")
    return approval


@router.post("/{token}/approve")
async def approve_price(token: str, body: DecisionBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.config import get_settings
    from app.services import background_jobs

    settings = get_settings()
    if settings.post_payment_background:
        # The manager only needs to know the approval was accepted. Building the
        # payment link and posting it to Bitrix takes several seconds, so it runs in
        # the background; the link, who it went to and its status show on the
        # developer page.
        try:
            approval = _check_can_decide(PriceApprovalService(db), token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        key = f"approval:{approval.id}"
        lead_id = approval.bitrix_lead_id
        live = background_jobs.get_job(key)
        if live is not None and live.state == background_jobs.STATE_RUNNING:
            return {"status": "approved", "queued": True, "lead_id": lead_id, "payment_url": None}

        prices = [p.model_dump() for p in body.product_prices]
        overrides = [i.model_dump() for i in body.installments]
        note = body.note

        async def _run() -> list[str]:
            with background_jobs.open_session() as bg:
                orchestrator = WorkflowOrchestrator(bg, settings)
                try:
                    await orchestrator.complete_approved_payment(
                        token,
                        note=note,
                        product_prices=prices,
                        installment_overrides=overrides,
                    )
                except CashCollectionQueued:
                    return []
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Approved, but the payment link was not created | lead=%s", lead_id)
                    reason = f"{type(exc).__name__}: {exc}"[:200]
                    try:
                        await orchestrator.bitrix.add_timeline_comment(
                            entity_type="LEAD",
                            entity_id=lead_id,
                            comment=(
                                "The manager approved this request, but the payment link "
                                f"could not be created: {reason}\nPlease move the lead to "
                                "the payment stage again to retry."
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Could not post the link failure on lead %s", lead_id)
                    return [reason]
            return []

        background_jobs.spawn(key, f"Payment link for lead {lead_id}", _run)
        return {
            "status": "approved",
            "queued": True,
            "cash_queued": False,
            "lead_id": lead_id,
            "payment_url": None,
            "message": "Approved. The payment link is being prepared and sent.",
        }

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
                "Collect cash in Finance."
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
