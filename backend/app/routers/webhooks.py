"""Webhook endpoints for Bitrix24 and Paymob."""

import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.integrations.paymob import extract_transaction_obj
from app.services.price_approval_service import PriceApprovalPending
from app.services.cash_collection_service import CashCollectionQueued
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
        # Only leads at the payment stage matter; the rest is background chatter.
        at_payment_stage = str(payload.get("STATUS_ID") or "") == settings.bitrix_lead_payment_stage_id
    elif entity_type == "deal":
        summary = _deal_summary(payload)
        at_payment_stage = True
    else:
        summary = {"keys": len(payload)}
        at_payment_stage = True

    log = logger.info if at_payment_stage else logger.debug
    log(
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


def _automation_document(payload: dict[str, Any]) -> tuple[str | None, int | None]:
    """Read the record a CRM automation robot fired for.

    Automation webhooks carry no `event`/`data[FIELDS]`; they identify the record as
    document_id[] = ("crm", "CCrmDocumentLead", "LEAD_107").
    """
    raw = payload.get("document_id")
    if isinstance(raw, dict):
        parts = [raw[key] for key in sorted(raw, key=lambda k: str(k))]
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        return None, None

    for part in reversed([str(p) for p in parts if p]):
        prefix, _, number = part.partition("_")
        if not number.isdigit():
            continue
        kind = prefix.strip().upper()
        if kind in ("LEAD", "DEAL"):
            return kind, int(number)
    return None, None


def _extract_lead_id(payload: dict[str, Any]) -> int | None:
    lead_id = _extract_entity_id(payload, "lead_id")
    if lead_id:
        return lead_id
    kind, doc_id = _automation_document(payload)
    return doc_id if kind == "LEAD" else None


def _extract_deal_id(payload: dict[str, Any]) -> int | None:
    deal_id = _extract_entity_id(payload, "deal_id")
    if deal_id:
        return deal_id
    kind, doc_id = _automation_document(payload)
    return doc_id if kind == "DEAL" else None


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
    # Every lead edit reaches us; stage-relevant lines are logged further down.
    logger.debug(
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
            db.commit()
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
        except CashCollectionQueued as exc:
            logger.info(
                "OK cash queued | request_id=%s deal_id=%s collection_id=%s",
                request_id,
                deal_id,
                exc.collection.id,
            )
            return {
                "status": "cash_queued",
                "deal_id": deal_id,
                "collection_id": exc.collection.id,
                "installment_number": exc.collection.installment_number,
                "due_amount": str(exc.collection.due_amount),
            }
        except ValueError as exc:
            logger.warning(
                "Bitrix payment link failed request_id=%s deal_id=%s reason=%s",
                request_id,
                deal_id,
                exc,
            )
            return {"status": "error", "reason": str(exc)}

    automation_kind, automation_id = _automation_document(payload)
    if automation_kind:
        logger.info(
            "Bitrix automation webhook | request_id=%s document=%s_%s",
            request_id,
            automation_kind,
            automation_id,
        )

    if (
        "lead" in event.lower()
        or payload.get("entity_type") == "lead"
        or automation_kind == "LEAD"
    ):
        lead_id = _extract_lead_id(payload)
        if not lead_id:
            logger.warning("Bitrix webhook ignored request_id=%s reason=missing_lead_id", request_id)
            return {"status": "ignored", "reason": "missing_lead_id"}

        lead = await _fetch_lead(orchestrator, lead_id)
        stage_id = str(lead.get("STATUS_ID") or "")
        summary = _lead_summary(lead)
        if stage_id != settings.bitrix_lead_payment_stage_id:
            # Bitrix fires on every lead edit; only the payment stage is interesting.
            logger.debug(
                "SKIP payment link | lead_id=%s title=%s stage=%s (need %s) amount=%s %s | reason=wrong_stage",
                lead_id,
                summary["title"],
                stage_id or "-",
                settings.bitrix_lead_payment_stage_id,
                summary["opportunity"],
                summary["currency"],
            )
            # Remember the move away so a return to the payment stage counts as new.
            orchestrator.note_lead_stage(lead_id, stage_id)
            return {
                "status": "ignored",
                "reason": "not_payment_stage",
                "lead_id": lead_id,
                "stage_id": stage_id or None,
            }

        logger.info(
            "START generate-payment-link | lead_id=%s title=%s stage=%s amount=%s %s email=%s",
            lead_id,
            summary["title"],
            stage_id,
            summary["opportunity"],
            summary["currency"],
            summary["email"],
        )

        workflow = orchestrator.get_or_create_workflow(lead_id)
        # Re-announce only when the lead truly re-enters this stage (not on every edit/comment).
        previous_stage = workflow.bitrix_lead_stage_id or ""
        entered_stage = previous_stage != stage_id
        active_session = orchestrator.session_service.get_active_session_for_workflow(workflow)
        if active_session:
            # Customer chooses payment mode on the link; do not replace the session
            # when Bitrix Payment Mode UF changes.
            await orchestrator.sync_workflow_from_lead(workflow, lead)
            payment_url = orchestrator.session_service.build_payment_url(
                active_session.token
            )
            # Our own timeline comments fire ONCRMLEADUPDATE. Without this
            # guard, force=True re-posts "Payment reminder" right after create.
            from datetime import datetime, timezone

            recently_commented = False
            if active_session.link_commented_at:
                commented_at = active_session.link_commented_at
                if commented_at.tzinfo is None:
                    commented_at = commented_at.replace(tzinfo=timezone.utc)
                recently_commented = (
                    datetime.now(timezone.utc) - commented_at
                ).total_seconds() < 600
            should_force = entered_stage and not recently_commented
            commented = await orchestrator.announce_payment_link(
                active_session,
                entity_type="LEAD",
                entity_id=lead_id,
                force=should_force,
            )
            orchestrator.note_lead_stage(lead_id, stage_id)
            logger.info(
                "SKIP new link | lead_id=%s title=%s | reason=link_already_active "
                "estimate_id=%s channel=%s commented=%s entered_stage=%s "
                "recently_commented=%s url=%s",
                lead_id,
                summary["title"],
                workflow.bitrix_estimate_id or "-",
                getattr(active_session, "channel", None) or "online",
                "yes" if commented else "already",
                entered_stage,
                recently_commented,
                payment_url,
            )
            return {
                "status": "ignored",
                "reason": "payment_link_already_active",
                "lead_id": lead_id,
                "payment_url": payment_url,
            }

        try:
            # Release the request DB connection before long Bitrix/Paymob work.
            db.commit()
            session = await orchestrator.initiate_payment_from_lead(lead_id, lead_data=lead)
        except PriceApprovalPending as exc:
            workflow = orchestrator.get_or_create_workflow(lead_id)
            orchestrator.note_lead_stage(lead_id, stage_id)
            logger.warning(
                "PENDING manager approval | lead_id=%s title=%s amount=%s estimate_id=%s "
                "approval_id=%s url=%s | %s",
                lead_id,
                summary["title"],
                summary["opportunity"],
                workflow.bitrix_estimate_id or "-",
                exc.approval_id,
                exc.approval_url,
                exc,
            )
            return {
                "status": "pending_approval",
                "reason": str(exc),
                "lead_id": lead_id,
                "estimate_id": workflow.bitrix_estimate_id,
                "approval_id": exc.approval_id,
                "approval_url": exc.approval_url,
            }
        except CashCollectionQueued as exc:
            logger.info(
                "OK cash queued | lead_id=%s title=%s collection_id=%s installment=%s amount=%s",
                lead_id,
                summary["title"],
                exc.collection.id,
                exc.collection.installment_number,
                exc.collection.due_amount,
            )
            return {
                "status": "cash_queued",
                "lead_id": lead_id,
                "collection_id": exc.collection.id,
                "installment_number": exc.collection.installment_number,
                "due_amount": str(exc.collection.due_amount),
            }
        except ValueError as exc:
            logger.warning(
                "FAIL payment link | lead_id=%s title=%s amount=%s | reason=%s",
                lead_id,
                summary["title"],
                summary["opportunity"],
                exc,
            )
            return {"status": "error", "reason": str(exc), "lead_id": lead_id}

        workflow = orchestrator.get_or_create_workflow(lead_id)
        orchestrator.note_lead_stage(lead_id, stage_id)
        payment_url = orchestrator.session_service.build_payment_url(session.token)
        logger.info(
            "OK payment link created | lead_id=%s title=%s stage=%s estimate_id=%s "
            "amount=%s %s email=%s url=%s",
            lead_id,
            summary["title"],
            stage_id,
            workflow.bitrix_estimate_id or "-",
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

    if (
        "deal" in event.lower()
        or payload.get("entity_type") == "deal"
        or automation_kind == "DEAL"
    ):
        deal_id = _extract_deal_id(payload)
        if not deal_id:
            logger.warning("Bitrix webhook ignored request_id=%s reason=missing_deal_id", request_id)
            return {"status": "ignored", "reason": "missing_deal_id"}

        # Always fetch the live deal so payment-link guard works even when
        # STAGE_ID arrived in the webhook payload (otherwise deal stays {}).
        payload_stage = stage_id
        fetched_stage, deal = await _resolve_deal_stage(orchestrator, deal_id)
        if not stage_id:
            stage_id = fetched_stage
        elif not deal:
            deal = {}

        if stage_id != settings.bitrix_finance_generate_link_stage_id:
            logger.debug(
                "SKIP payment link | deal_id=%s stage=%s payload_stage=%s (need %s) | reason=wrong_stage",
                deal_id,
                stage_id or "-",
                payload_stage or "-",
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
                commented = await orchestrator.announce_payment_link(
                    active_session, entity_type="DEAL", entity_id=deal_id
                )
                logger.info(
                    "SKIP new link | deal_id=%s | reason=link_already_active commented=%s url=%s",
                    deal_id,
                    "yes" if commented else "already",
                    existing_link,
                )
                return {
                    "status": "ignored",
                    "reason": "payment_link_already_active",
                    "deal_id": deal_id,
                    "payment_url": existing_link,
                }

        try:
            # Release the request DB connection before long Bitrix/Paymob work.
            db.commit()
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
        except CashCollectionQueued as exc:
            logger.info(
                "OK cash queued | request_id=%s deal_id=%s collection_id=%s",
                request_id,
                deal_id,
                exc.collection.id,
            )
            return {
                "status": "cash_queued",
                "deal_id": deal_id,
                "collection_id": exc.collection.id,
                "installment_number": exc.collection.installment_number,
                "due_amount": str(exc.collection.due_amount),
            }
        except ValueError as exc:
            logger.warning(
                "Bitrix deal failed request_id=%s deal_id=%s reason=%s",
                request_id,
                deal_id,
                exc,
            )
            return {"status": "error", "reason": str(exc)}

    # Logged loudly: an unrecognised shape means a configured trigger is doing nothing.
    logger.warning(
        "Bitrix webhook ignored | request_id=%s reason=unhandled_event event=%s keys=%s",
        request_id,
        event or "-",
        sorted(payload.keys()),
    )
    return {"status": "ignored", "reason": "unhandled_event", "event": event}


@router.post("/paymob")
async def paymob_webhook(
    request: Request,
    db: Session = Depends(get_db),
    hmac: str | None = Header(default=None, alias="HMAC"),
) -> dict[str, Any]:
    request_id = uuid4().hex[:12]
    settings = get_settings()
    raw_body = await request.body()
    payload_format = "json"

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except ValueError:
        payload_format = "form"
        form = await request.form()
        payload = _expand_bracket_keys(dict(form))

    if not isinstance(payload, dict) or not payload:
        logger.warning(
            "Paymob webhook ignored | request_id=%s reason=empty_or_invalid_body "
            "content_type=%s body_bytes=%s",
            request_id,
            request.headers.get("content-type") or "-",
            len(raw_body),
        )
        return {"status": "ignored", "reason": "empty_body"}

    # UAE Intention callbacks carry the HMAC in the JSON body; legacy uses header/query.
    if hmac:
        signature_source = "header"
        signature = hmac
    elif request.query_params.get("hmac"):
        signature_source = "query"
        signature = request.query_params["hmac"]
    elif payload.get("hmac"):
        signature_source = "body"
        signature = str(payload["hmac"])
    else:
        signature_source = "missing"
        signature = None

    obj = extract_transaction_obj(payload)
    intention = payload.get("intention") if isinstance(payload.get("intention"), dict) else {}
    ref = (
        ((obj.get("order") or {}).get("merchant_order_id") if isinstance(obj.get("order"), dict) else None)
        or intention.get("special_reference")
        or "-"
    )
    payload_shape = (
        "obj"
        if isinstance(payload.get("obj"), dict)
        else "transaction"
        if isinstance(payload.get("transaction"), dict)
        else "root"
    )
    logger.info(
        "Paymob webhook received | request_id=%s txn=%s ref=%s amount=%s %s "
        "success=%s pending=%s format=%s shape=%s signature=%s body_bytes=%s",
        request_id,
        obj.get("id") or "-",
        ref,
        obj.get("amount_cents") or "-",
        obj.get("currency") or "-",
        obj.get("success"),
        obj.get("pending"),
        payload_format,
        payload_shape,
        signature_source,
        len(raw_body),
    )

    if obj.get("id") is None:
        logger.warning(
            "Paymob webhook ignored | request_id=%s reason=not_a_transaction "
            "payload_keys=%s transaction_keys=%s",
            request_id,
            sorted(payload.keys()),
            sorted(obj.keys()),
        )
        return {"status": "ignored", "reason": "not_a_transaction"}

    if not signature:
        logger.warning(
            "Paymob webhook rejected | request_id=%s txn=%s reason=missing_hmac "
            "expected=header_query_or_body",
            request_id,
            obj.get("id"),
        )
        raise HTTPException(status_code=401, detail="Missing Paymob HMAC")

    orchestrator = WorkflowOrchestrator(db)
    try:
        workflow = await orchestrator.handle_paymob_payload(payload, signature)
    except ValueError as exc:
        logger.warning(
            "Paymob webhook rejected | request_id=%s txn=%s reason=%s",
            request_id,
            obj.get("id") or "-",
            exc,
        )
        if settings.log_paymob_payloads:
            # Opt-in: the raw body pins down which fields Paymob actually signed.
            logger.warning(
                "Paymob rejected raw body | request_id=%s body=%s",
                request_id,
                raw_body[:8000].decode("utf-8", "replace"),
            )
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception:
        logger.exception(
            "Paymob webhook processing failed | request_id=%s txn=%s ref=%s",
            request_id,
            obj.get("id") or "-",
            ref,
        )
        raise

    if workflow is None:
        logger.info(
            "Paymob webhook ignored | request_id=%s txn=%s "
            "reason=failed_pending_or_duplicate success=%s pending=%s",
            request_id,
            obj.get("id") or "-",
            obj.get("success"),
            obj.get("pending"),
        )
        return {"status": "ignored", "reason": "no_successful_transaction_or_duplicate"}

    logger.info(
        "OK payment received | request_id=%s txn=%s lead_id=%s "
        "paid=%s remaining=%s status=%s",
        request_id,
        obj.get("id") or "-",
        workflow.bitrix_lead_id,
        workflow.amount_paid,
        workflow.remaining_balance,
        workflow.payment_status,
    )
    return {
        "status": "processed",
        "workflow_id": workflow.id,
        "amount_paid": str(workflow.amount_paid),
        "remaining_balance": str(workflow.remaining_balance),
        "zoho_invoice_id": workflow.zoho_invoice_id,
        "payment_status": workflow.payment_status,
    }


@router.get("/paymob")
async def paymob_webhook_get() -> dict[str, str]:
    return {"status": "ok", "message": "Paymob webhook endpoint is active"}
