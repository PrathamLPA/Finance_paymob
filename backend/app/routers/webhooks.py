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


def _expand_bracket_keys(flat: dict[str, Any]) -> dict[str, Any]:
    """Turn Bitrix form keys like data[FIELDS][ID] into nested dicts."""
    nested: dict[str, Any] = {}
    for raw_key, value in flat.items():
        if "[" not in raw_key:
            nested[raw_key] = value
            continue

        head, _, rest = raw_key.partition("[")
        parts = [head] + [segment.rstrip("]") for segment in rest.split("[") if segment]
        cursor = nested
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = value
    return nested


async def _read_payload(request: Request) -> dict[str, Any]:
    """Bitrix outbound webhooks post form-encoded data; dev/tests post JSON."""
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    form = await request.form()
    if form:
        return _expand_bracket_keys({key: form[key] for key in form.keys()})

    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _authorize(request: Request, payload: dict[str, Any]) -> None:
    """Accept either the Bitrix application token or the legacy header secret."""
    settings = get_settings()
    expected = settings.bitrix_webhook_secret
    if not expected:
        return

    auth = payload.get("auth") or {}
    application_token = auth.get("application_token") or payload.get("application_token")
    header_secret = request.headers.get("X-Webhook-Secret")

    if application_token == expected or header_secret == expected:
        return

    raise HTTPException(status_code=401, detail="Invalid webhook token")


def _fields(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    fields = data.get("FIELDS") or data.get("fields") or {}
    return fields if isinstance(fields, dict) else {}


def _extract_entity_id(payload: dict[str, Any], *fallback_keys: str) -> int | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    candidates = [_fields(payload).get("ID"), data.get("ID")]
    candidates.extend(payload.get(key) for key in fallback_keys)
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _extract_lead_id(payload: dict[str, Any]) -> int | None:
    return _extract_entity_id(payload, "lead_id")


def _extract_deal_id(payload: dict[str, Any]) -> int | None:
    return _extract_entity_id(payload, "deal_id")


def _extract_stage_id(payload: dict[str, Any]) -> str | None:
    fields = _fields(payload)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    stage_id = (
        fields.get("STAGE_ID")
        or fields.get("STATUS_ID")
        or data.get("STAGE_ID")
        or payload.get("stage_id")
    )
    return str(stage_id) if stage_id else None


async def _resolve_deal_stage(orchestrator: WorkflowOrchestrator, deal_id: int) -> tuple[str | None, dict[str, Any]]:
    """Bitrix rarely sends STAGE_ID on update, so read the current deal."""
    try:
        deal = await orchestrator.bitrix.get_deal(deal_id)
    except Exception:
        logger.exception("Failed to fetch Bitrix deal %s", deal_id)
        return None, {}
    stage_id = deal.get("STAGE_ID")
    return (str(stage_id) if stage_id else None), deal


async def _fetch_lead(orchestrator: WorkflowOrchestrator, lead_id: int) -> dict[str, Any]:
    """Fetch the complete current lead; webhook fields are not authoritative."""
    try:
        return await orchestrator.bitrix.get_lead(lead_id)
    except Exception as exc:
        logger.exception("Failed to fetch Bitrix lead %s", lead_id)
        raise HTTPException(status_code=502, detail="Could not fetch lead from Bitrix") from exc


@router.post("/bitrix24")
async def bitrix24_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    payload = await _read_payload(request)
    _authorize(request, payload)

    orchestrator = WorkflowOrchestrator(db)
    event = str(payload.get("event") or payload.get("EVENT") or "")
    action = str(payload.get("action") or payload.get("ACTION") or "")
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

        lead = await _fetch_lead(orchestrator, lead_id)
        stage_id = str(lead.get("STATUS_ID") or "")
        if stage_id != settings.bitrix_lead_payment_stage_id:
            return {
                "status": "ignored",
                "reason": "not_payment_stage",
                "lead_id": lead_id,
                "stage_id": stage_id or None,
            }

        workflow = orchestrator.get_or_create_workflow(lead_id)
        active_session = orchestrator.session_service.get_active_session_for_workflow(workflow)
        if active_session:
            await orchestrator.sync_workflow_from_lead(workflow, lead)
            return {
                "status": "ignored",
                "reason": "payment_link_already_active",
                "lead_id": lead_id,
                "payment_url": orchestrator.session_service.build_payment_url(active_session.token),
            }

        session = await orchestrator.initiate_payment_from_lead(lead_id, lead_data=lead)
        return {
            "status": "processed",
            "source": "lead_stage",
            "lead_id": lead_id,
            "stored_fields": len(lead),
            "payment_url": orchestrator.session_service.build_payment_url(session.token),
        }

    if "deal" in event.lower() or payload.get("entity_type") == "deal":
        deal_id = _extract_deal_id(payload)
        if not deal_id:
            return {"status": "ignored", "reason": "missing_deal_id"}

        deal: dict[str, Any] = {}
        if not stage_id:
            stage_id, deal = await _resolve_deal_stage(orchestrator, deal_id)

        if stage_id != settings.bitrix_finance_generate_link_stage_id:
            return {"status": "ignored", "reason": "not_generate_link_stage", "stage_id": stage_id}

        # ONCRMDEALUPDATE also fires for our own payment-link write; don't loop.
        existing_link = deal.get(settings.bitrix_field_payment_link)
        if existing_link:
            workflow = orchestrator.get_workflow_by_finance_deal(deal_id)
            active_session = (
                orchestrator.session_service.get_active_session_for_workflow(workflow) if workflow else None
            )
            if active_session:
                return {
                    "status": "ignored",
                    "reason": "payment_link_already_active",
                    "deal_id": deal_id,
                    "payment_url": existing_link,
                }

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
