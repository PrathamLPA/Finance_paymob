"""Development and testing helper endpoints."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.factory import get_bitrix_client
from app.services.seed_mock_data import seed_mock_data
from app.services.workflow_orchestrator import WorkflowOrchestrator

router = APIRouter(prefix="/api/dev", tags=["dev"])


class SendPaymentLinkRequest(BaseModel):
    lead_id: int | None = None
    finance_deal_id: int | None = None
    customer_email: str | None = None
    customer_name: str | None = None
    total_amount: Decimal | None = Field(default=None, description="Optional total for new leads")


class SimulatePaymobRequest(BaseModel):
    token: str | None = None
    merchant_reference: str | None = None
    amount: Decimal | None = None


@router.post("/send-payment-link")
async def send_payment_link(
    body: SendPaymentLinkRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    orchestrator = WorkflowOrchestrator(db)

    if body.lead_id:
        override_kwargs: dict[str, Any] = {}
        if body.customer_email and body.customer_name and body.total_amount is not None:
            override_kwargs = {
                "customer_email": body.customer_email,
                "customer_name": body.customer_name,
                "total_amount": body.total_amount,
            }
        else:
            bitrix = get_bitrix_client()
            if hasattr(bitrix, "seed_lead") and body.customer_email:
                bitrix.seed_lead(
                    body.lead_id,
                    email=body.customer_email,
                    name=body.customer_name or "Test Customer",
                    amount=body.total_amount or Decimal("10000.00"),
                )
        session = await orchestrator.initiate_payment_from_lead(body.lead_id, **override_kwargs)
        return {
            "status": "ok",
            "source": "lead",
            "lead_id": body.lead_id,
            "token": session.token,
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
            "merchant_reference": session.merchant_reference,
        }

    if body.finance_deal_id:
        try:
            session = await orchestrator.initiate_payment_from_finance_deal(body.finance_deal_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "status": "ok",
            "source": "finance_deal",
            "finance_deal_id": body.finance_deal_id,
            "token": session.token,
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
            "merchant_reference": session.merchant_reference,
        }

    raise HTTPException(status_code=400, detail="Provide lead_id or finance_deal_id")


@router.post("/simulate-paymob-webhook")
async def simulate_paymob_webhook(
    body: SimulatePaymobRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not body.token and not body.merchant_reference:
        raise HTTPException(status_code=400, detail="Provide token or merchant_reference")

    orchestrator = WorkflowOrchestrator(db)
    try:
        workflow = await orchestrator.simulate_payment(
            token=body.token,
            merchant_reference=body.merchant_reference,
            amount=body.amount,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if workflow is None:
        return {"status": "duplicate", "reason": "transaction already processed"}

    return {
        "status": "ok",
        "workflow_id": workflow.id,
        "sales_deal_id": workflow.sales_deal_id,
        "finance_deal_id": workflow.finance_deal_id,
        "b2c_deal_id": workflow.b2c_deal_id,
        "zoho_invoice_id": workflow.zoho_invoice_id,
        "amount_paid": str(workflow.amount_paid),
        "remaining_balance": str(workflow.remaining_balance),
    }


@router.post("/seed-mock-data")
async def seed_mock_customers(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Seed mock customers with Paymob-shaped payment data for Supabase visualization."""
    return seed_mock_data(db)
