"""Webhook endpoints for Bitrix24 and Paymob."""

import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.services.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _redact_sensitive(value: Any) -> Any:
    """Redact credentials while preserving CRM fields for temporary diagnostics."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).lower()
            if any(word in normalized for word in ("token", "password", "secret", "authorization")):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = _redact_sensitive(child)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _lead_summary(lead: dict[str, Any]) -> dict[str, Any]:
    email = None
    emails = lead.get("EMAIL") or []
    if isinstance(emails, list) and emails:
        email = emails[0].get("VALUE")
    phone = None
    phones = lead.get("PHONE") or []
    if isinstance(phones, list) and phones:
        phone = phones[0].get("VALUE")
    return {
        "title": lead.get("TITLE") or "-",
        "stage": lead.get("STATUS_ID") or "-",
        "opportunity": lead.get("OPPORTUNITY") or "0",
        "currency": lead.get("CURRENCY_ID") or "-",
        "email": email or "-",
        "phone": phone or "-",
        "name": " ".join(
            p for p in (lead.get("NAME"), lead.get("LAST_NAME")) if p
        ).strip()
        or "-",
    }


def _deal_summary(deal: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": deal.get("TITLE") or "-",
        "stage": deal.get("STAGE_ID") or "-",
        "opportunity": deal.get("OPPORTUNITY") or "-",
        "currency": deal.get("CURRENCY_ID") or "-",
    }


def _log_bitrix_entity(entity_type: str, entity_id: int, payload: dict[str, Any]) -> None:
    """Log a short CRM summary; full payload only when LOG_BITRIX_PAYLOADS=true."""
    settings = get_settings()
    if entity_type == "lead":
        summary = _lead_summary(payload)
    elif entity_type == "deal":
        summary = _deal_summary(payload)
    else:
        summary = {"keys": len(payload)}

    logger.info(
        "Bitrix %s fetched id=%s title=%s stage=%s amount=%s %s email=%s",
        entity_type,
        entity_id,
        summary.get("title", "-"),
        summary.get("stage", "-"),
        summary.get("opportunity", "-"),
        summary.get("currency", "-"),
        summary.get("email", "-"),
    )

    if not settings.log_bitrix_payloads:
        return
    # Opt-in dump for deep debugging only — keep it short in the main log stream.
    logger.debug(
        "Bitrix %s full payload id=%s keys=%s payload=%s",
        entity_type,
        entity_id,
        sorted(payload.keys()),
        json.dumps(_redact_sensitive(payload), default=str, ensure_ascii=False)[:4000],
    )


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

    logger.warning(
        "Bitrix webhook authentication rejected content_type=%s",
        request.headers.get("content-type"),
    )
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
    _log_bitrix_entity("deal", deal_id, deal)
    stage_id = deal.get("STAGE_ID")
    return (str(stage_id) if stage_id else None), deal


async def _fetch_lead(orchestrator: WorkflowOrchestrator, lead_id: int) -> dict[str, Any]:
    """Fetch the complete current lead; webhook fields are not authoritative."""
    try:
        lead = await orchestrator.bitrix.get_lead(lead_id)
    except Exception as exc:
        logger.exception("Failed to fetch Bitrix lead %s", lead_id)
        raise HTTPException(status_code=502, detail="Could not fetch lead from Bitrix") from exc
    _log_bitrix_entity("lead", lead_id, lead)
    return lead


@router.post("/bitrix24")
async def bitrix24_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request_id = uuid4().hex[:12]
    settings = get_settings()
    payload = await _read_payload(request)
    _authorize(request, payload)

    orchestrator = WorkflowOrchestrator(db)
    event = str(payload.get("event") or payload.get("EVENT") or "")
    action = str(payload.get("action") or payload.get("ACTION") or "")
    stage_id = _extract_stage_id(payload)
    logger.info(
        "Bitrix webhook received request_id=%s event=%s action=%s content_type=%s",
        request_id,
        event or "-",
        action or "-",
        request.headers.get("content-type") or "-",
    )

    if action == "send_payment_link" or payload.get("send_payment_link"):
        deal_id = _extract_deal_id(payload)
        if not deal_id:
            logger.warning("Bitrix webhook ignored request_id=%s reason=missing_deal_id", request_id)
            return {"status": "ignored", "reason": "missing_deal_id"}
        try:
            session = await orchestrator.initiate_payment_from_finance_deal(deal_id)
            logger.info(
                "Bitrix payment link processed request_id=%s source=button deal_id=%s session_id=%s",
                request_id,
                deal_id,
                session.id,
            )
            return {
                "status": "processed",
                "source": "finance_deal_button",
                "deal_id": deal_id,
                "payment_url": orchestrator.session_service.build_payment_url(session.token),
            }
        except ValueError as exc:
            logger.warning(
                "Bitrix payment link failed request_id=%s deal_id=%s reason=%s",
                request_id,
                deal_id,
                exc,
            )
            return {"status": "error", "reason": str(exc)}

    if "lead" in event.lower() or payload.get("entity_type") == "lead":
        lead_id = _extract_lead_id(payload)
        if not lead_id:
            logger.warning("Bitrix webhook ignored request_id=%s reason=missing_lead_id", request_id)
            return {"status": "ignored", "reason": "missing_lead_id"}

        lead = await _fetch_lead(orchestrator, lead_id)
        stage_id = str(lead.get("STATUS_ID") or "")
        summary = _lead_summary(lead)
        if stage_id != settings.bitrix_lead_payment_stage_id:
            logger.info(
                "SKIP payment link | lead_id=%s title=%s stage=%s (need %s) amount=%s %s | reason=wrong_stage",
                lead_id,
                summary["title"],
                stage_id or "-",
                settings.bitrix_lead_payment_stage_id,
                summary["opportunity"],
                summary["currency"],
            )
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
            payment_url = orchestrator.session_service.build_payment_url(active_session.token)
            logger.info(
                "SKIP new link | lead_id=%s title=%s | reason=link_already_active url=%s",
                lead_id,
                summary["title"],
                payment_url,
            )
            return {
                "status": "ignored",
                "reason": "payment_link_already_active",
                "lead_id": lead_id,
                "payment_url": payment_url,
            }

        try:
            session = await orchestrator.initiate_payment_from_lead(lead_id, lead_data=lead)
        except ValueError as exc:
            logger.warning(
                "FAIL payment link | lead_id=%s title=%s amount=%s | reason=%s",
                lead_id,
                summary["title"],
                summary["opportunity"],
                exc,
            )
            return {"status": "error", "reason": str(exc), "lead_id": lead_id}

        payment_url = orchestrator.session_service.build_payment_url(session.token)
        logger.info(
            "OK payment link created | lead_id=%s title=%s stage=%s amount=%s %s email=%s url=%s",
            lead_id,
            summary["title"],
            stage_id,
            summary["opportunity"],
            summary["currency"],
            summary["email"],
            payment_url,
        )
        return {
            "status": "processed",
            "source": "lead_stage",
            "lead_id": lead_id,
            "stored_fields": len(lead),
            "payment_url": payment_url,
        }

    if "deal" in event.lower() or payload.get("entity_type") == "deal":
        deal_id = _extract_deal_id(payload)
        if not deal_id:
            logger.warning("Bitrix webhook ignored request_id=%s reason=missing_deal_id", request_id)
            return {"status": "ignored", "reason": "missing_deal_id"}

        deal: dict[str, Any] = {}
        if not stage_id:
            stage_id, deal = await _resolve_deal_stage(orchestrator, deal_id)

        if stage_id != settings.bitrix_finance_generate_link_stage_id:
            logger.info(
                "SKIP payment link | deal_id=%s stage=%s (need %s) | reason=wrong_stage",
                deal_id,
                stage_id or "-",
                settings.bitrix_finance_generate_link_stage_id,
            )
            return {"status": "ignored", "reason": "not_generate_link_stage", "stage_id": stage_id}

        # ONCRMDEALUPDATE also fires for our own payment-link write; don't loop.
        existing_link = deal.get(settings.bitrix_field_payment_link)
        if existing_link:
            workflow = orchestrator.get_workflow_by_finance_deal(deal_id)
            active_session = (
                orchestrator.session_service.get_active_session_for_workflow(workflow) if workflow else None
            )
            if active_session:
                logger.info(
                    "SKIP new link | deal_id=%s | reason=link_already_active url=%s",
                    deal_id,
                    existing_link,
                )
                return {
                    "status": "ignored",
                    "reason": "payment_link_already_active",
                    "deal_id": deal_id,
                    "payment_url": existing_link,
                }

        try:
            session = await orchestrator.initiate_payment_from_finance_deal(deal_id)
            payment_url = orchestrator.session_service.build_payment_url(session.token)
            logger.info(
                "OK payment link created | deal_id=%s stage=%s url=%s",
                deal_id,
                stage_id,
                payment_url,
            )
            return {
                "status": "processed",
                "source": "finance_deal_stage",
                "deal_id": deal_id,
                "payment_url": payment_url,
            }
        except ValueError as exc:
            logger.warning(
                "Bitrix deal failed request_id=%s deal_id=%s reason=%s",
                request_id,
                deal_id,
                exc,
            )
            return {"status": "error", "reason": str(exc)}

    logger.info(
        "Bitrix webhook ignored request_id=%s reason=unhandled_event event=%s",
        request_id,
        event or "-",
    )
    return {"status": "ignored", "reason": "unhandled_event", "event": event}


@router.post("/paymob")
async def paymob_webhook(
    request: Request,
    db: Session = Depends(get_db),
    hmac: str | None = Header(default=None, alias="HMAC"),
) -> dict[str, Any]:
    request_id = uuid4().hex[:12]
    logger.info("Paymob webhook received request_id=%s", request_id)
    payload = await request.json()
    orchestrator = WorkflowOrchestrator(db)

    try:
        workflow = await orchestrator.handle_paymob_payload(payload, hmac)
    except ValueError as exc:
        logger.warning("Paymob webhook rejected request_id=%s reason=%s", request_id, exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if workflow is None:
        logger.info(
            "Paymob webhook ignored request_id=%s reason=no_successful_transaction_or_duplicate",
            request_id,
        )
        return {"status": "ignored", "reason": "no_successful_transaction_or_duplicate"}

    logger.info(
        "Paymob webhook processed request_id=%s workflow_id=%s amount_paid=%s remaining_balance=%s",
        request_id,
        workflow.id,
        workflow.amount_paid,
        workflow.remaining_balance,
    )
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
