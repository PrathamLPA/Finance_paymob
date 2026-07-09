"""Webhook endpoints for Bitrix24 and Paymob."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.services.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _extract_lead_id(payload: dict[str, Any]) -> int | None:
    data = payload.get("data") or {}
    fields = data.get("FIELDS") or data.get("fields") or {}
    lead_id = fields.get("ID") or data.get("ID") or payload.get("lead_id")
    if lead_id:
        return int(lead_id)
    return None


def _extract_deal_id(payload: dict[str, Any]) -> int | None:
    data = payload.get("data") or {}
    fields = data.get("FIELDS") or data.get("fields") or {}
    deal_id = fields.get("ID") or data.get("ID") or payload.get("deal_id")
    if deal_id:
        return int(deal_id)
    return None


def _extract_stage_id(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") or {}
    fields = data.get("FIELDS") or data.get("fields") or {}
    stage_id = fields.get("STAGE_ID") or fields.get("STATUS_ID") or data.get("STAGE_ID") or payload.get("stage_id")
    return str(stage_id) if stage_id else None


@router.post("/bitrix24")
async def bitrix24_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    payload = await request.json()

    if settings.bitrix_webhook_secret:
        provided = request.headers.get("X-Webhook-Secret")
        if provided != settings.bitrix_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    orchestrator = WorkflowOrchestrator(db)
    event = payload.get("event") or payload.get("EVENT") or ""
    action = payload.get("action") or payload.get("ACTION") or ""
    stage_id = _extract_stage_id(payload)

    if action == "send_payment_link" or payload.get("send_payment_link"):
        deal_id = _extract_deal_id(payload)
        if not deal_id:
            return {"status": "ignored", "reason": "missing_deal_id"}
        try:
            session = await orchestrator.initiate_payment_from_finance_deal(deal_id)
            return {
                "status": "processed",
                "source": "finance_deal_button",
                "deal_id": deal_id,
                "payment_url": orchestrator.session_service.build_payment_url(session.token),
            }
        except ValueError as exc:
            return {"status": "error", "reason": str(exc)}

    if "lead" in event.lower() or payload.get("entity_type") == "lead":
        lead_id = _extract_lead_id(payload)
        if not lead_id:
            return {"status": "ignored", "reason": "missing_lead_id"}

        if stage_id and stage_id != settings.bitrix_lead_payment_stage_id:
            return {"status": "ignored", "reason": "not_payment_stage", "stage_id": stage_id}

        session = await orchestrator.initiate_payment_from_lead(lead_id)
        return {
            "status": "processed",
            "source": "lead_stage",
            "lead_id": lead_id,
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
        }

    if "deal" in event.lower() or payload.get("entity_type") == "deal":
        deal_id = _extract_deal_id(payload)
        if not deal_id:
            return {"status": "ignored", "reason": "missing_deal_id"}

        if stage_id and stage_id != settings.bitrix_finance_generate_link_stage_id:
            return {"status": "ignored", "reason": "not_generate_link_stage", "stage_id": stage_id}

        try:
            session = await orchestrator.initiate_payment_from_finance_deal(deal_id)
            return {
                "status": "processed",
                "source": "finance_deal_stage",
                "deal_id": deal_id,
                "payment_url": orchestrator.session_service.build_payment_url(session.token),
            }
        except ValueError as exc:
            return {"status": "error", "reason": str(exc)}

    lead_id = _extract_lead_id(payload)
    if lead_id and (not stage_id or stage_id == settings.bitrix_lead_payment_stage_id):
        session = await orchestrator.initiate_payment_from_lead(lead_id)
        return {
            "status": "processed",
            "source": "lead_fallback",
            "lead_id": lead_id,
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
        }

    return {"status": "ignored", "reason": "unhandled_event", "event": event}


@router.post("/paymob")
async def paymob_webhook(
    request: Request,
    db: Session = Depends(get_db),
    hmac: str | None = Header(default=None, alias="HMAC"),
) -> dict[str, Any]:
    payload = await request.json()
    orchestrator = WorkflowOrchestrator(db)

    try:
        workflow = await orchestrator.handle_paymob_payload(payload, hmac)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if workflow is None:
        return {"status": "ignored", "reason": "no_successful_transaction_or_duplicate"}

    return {
        "status": "processed",
        "workflow_id": workflow.id,
        "amount_paid": str(workflow.amount_paid),
        "remaining_balance": str(workflow.remaining_balance),
        "zoho_invoice_id": workflow.zoho_invoice_id,
    }


@router.get("/paymob")
async def paymob_webhook_get() -> dict[str, str]:
    return {"status": "ok", "message": "Paymob webhook endpoint is active"}
