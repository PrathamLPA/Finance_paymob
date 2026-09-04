"""JSON payment APIs consumed by the separate frontend service."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db.session import get_db
from app.integrations.factory import get_bitrix_client
from app.models.payment_session import CHANNEL_BANK_TRANSFER, PaymentSession, SESSION_TERMS_ACCEPTED
from app.services.bank_transfer_service import BankTransferService
from app.services.course_seats import load_lead_courses, total_seats
from app.services.installment_plan import schedule_payload
from app.services.payment_session_service import PaymentSessionService
from app.services.terms_service import TermsService

router = APIRouter(prefix="/api/payment", tags=["payment-api"])


class ParticipantBody(BaseModel):
    name: str = ""
    email: str = ""
    product_id: int = 0
    product_name: str = ""


class AcceptTermsBody(BaseModel):
    accepted: bool = False
    course_for: str = ""
    registrant_name: str = ""
    registrant_email: str = ""
    registrant_phone: str = ""
    payment_amount: Decimal | None = None
    payment_mode: str = ""
    participants: list[ParticipantBody] = Field(default_factory=list)


@router.get("/lookup/{merchant_reference}")
async def lookup_payment_by_reference(
    merchant_reference: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Public thank-you helper: who the course is for + LMS link when self."""
    ref = (merchant_reference or "").strip()
    if not ref:
        raise HTTPException(status_code=404, detail="Payment reference not found.")

    session = db.scalar(
        select(PaymentSession)
        .options(joinedload(PaymentSession.terms_acceptance))
        .where(PaymentSession.merchant_reference == ref)
    )
    if not session:
        raise HTTPException(status_code=404, detail="Payment reference not found.")

    settings = get_settings()
    course_for = None
    if session.terms_acceptance:
        course_for = session.terms_acceptance.course_for
    show_lms = course_for == "self"
    return {
        "merchant_reference": session.merchant_reference,
        "course_for": course_for,
        "show_lms": show_lms,
        "lms_url": settings.lms_login_url if show_lms else None,
    }


@router.get("/{token}")
async def get_payment_session(token: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session_service = PaymentSessionService(db)
    session = session_service.get_active_session_by_token(token)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=session_service.describe_inactive_token(token),
        )
    terms_service = TermsService(db)
    context = terms_service.get_terms_context()
    workflow = session.workflow
    required_percent = session_service.settings.payment_required_percent
    locked = bool(getattr(session, "amount_locked", True))
    charge_source = getattr(session, "charge_source", None) or "full"
    installment_number = getattr(session, "installment_number", None)
    channel = getattr(session, "channel", None) or "online"
    schedule = schedule_payload(workflow)
    installment_count = len(schedule) or None
    current_due_date = None
    if installment_number and schedule:
        for row in schedule:
            if row["number"] == installment_number:
                current_due_date = row["due_date"]
                break
    if charge_source == "installment_1":
        charge_label = (
            f"Installment {installment_number or 1}"
            + (f" of {installment_count}" if installment_count else "")
        )
    else:
        charge_label = "Full payment"

    pricing = workflow.pricing_snapshot or {}
    payment_amount = Decimal(session.charge_amount)
    balance_after = max(workflow.remaining_balance - payment_amount, Decimal("0.00"))

    bank_transfer: dict[str, Any] | None = None
    if channel == CHANNEL_BANK_TRANSFER:
        bt = BankTransferService(db)
        submission = bt.get_by_session(session)
        settings = session_service.settings
        bank_transfer = {
            "status": submission.status if submission else "awaiting_upload",
            "instructions": settings.bank_transfer_instructions,
            "has_proof": bool(submission and submission.proof_path),
            "receipt_upload_url": session_service.build_receipt_upload_url(token),
            "submission_id": submission.id if submission else None,
        }

    bitrix = get_bitrix_client(session_service.settings)
    courses = await load_lead_courses(bitrix, workflow.bitrix_lead_id)
    return {
        "token": token,
        "status": session.status,
        "channel": channel,
        "bank_transfer": bank_transfer,
        "terms_version": context["terms_version"],
        "terms_html": context["terms_html"],
        "refund_policy_url": context["refund_policy_url"],
        "currency": workflow.currency,
        "total_amount": str(workflow.total_amount),
        "amount_paid": str(workflow.amount_paid),
        "remaining_balance": str(workflow.remaining_balance),
        "minimum_amount": str(session.charge_amount if locked else workflow.minimum_due(required_percent)),
        "payment_amount": str(session.charge_amount),
        "balance_after_payment": str(balance_after.quantize(Decimal("0.01"))),
        "allows_partial": False if locked else (
            workflow.minimum_due(required_percent) < workflow.remaining_balance
        ),
        "amount_locked": locked,
        "charge_source": charge_source,
        "charge_label": charge_label,
        "installment_number": installment_number,
        "installment_count": installment_count,
        "installment_due_date": current_due_date,
        "installment_schedule": schedule,
        "subtotal": str(pricing.get("subtotal") or workflow.total_amount),
        "vat_total": str(pricing.get("vat_total") or pricing.get("tax_total") or "0.00"),
        "tax_total": str(pricing.get("tax_total") or pricing.get("vat_total") or "0.00"),
        "pricing_lines": pricing.get("lines") or [],
        "required_percent": str(required_percent),
        "courses": courses,
        "total_seats": total_seats(courses),
        "customer_name": workflow.customer_name,
        "customer_email": workflow.customer_email,
        "customer_phone": workflow.customer_phone,
    }


@router.post("/{token}/accept")
async def accept_payment_terms(
    token: str,
    request: Request,
    body: AcceptTermsBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not body.accepted:
        raise HTTPException(status_code=400, detail="You must accept the Terms and Conditions to continue.")

    terms_service = TermsService(db)
    client_ip = request.client.host if request.client else None
    checkout_url = await terms_service.accept_terms(
        token,
        accepted=True,
        ip_address=client_ip,
        course_for=body.course_for,
        registrant_name=body.registrant_name,
        registrant_email=body.registrant_email,
        registrant_phone=body.registrant_phone,
        payment_amount=body.payment_amount,
        payment_mode=body.payment_mode,
        participants=[p.model_dump() for p in body.participants],
        background_tasks=background_tasks,
    )
    return {"checkout_url": checkout_url}


@router.get("/{token}/receipt")
async def get_receipt_upload_context(
    token: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    session_service = PaymentSessionService(db)
    session = session_service.get_active_session_by_token(token)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=session_service.describe_inactive_token(token),
        )
    if (getattr(session, "channel", None) or "") != CHANNEL_BANK_TRANSFER:
        raise HTTPException(status_code=400, detail="This payment link is not for bank transfer.")
    if session.status not in (SESSION_TERMS_ACCEPTED,):
        raise HTTPException(
            status_code=400,
            detail="Please accept the Terms and Conditions before uploading a receipt.",
        )

    bt = BankTransferService(db, session_service.settings)
    submission = bt.get_by_session(session) or bt.enqueue_for_session(session)
    workflow = session.workflow
    return {
        "token": token,
        "status": submission.status,
        "channel": CHANNEL_BANK_TRANSFER,
        "instructions": session_service.settings.bank_transfer_instructions,
        "currency": session.currency,
        "payment_amount": str(session.charge_amount),
        "customer_name": workflow.customer_name if workflow else None,
        "customer_email": workflow.customer_email if workflow else None,
        "has_proof": bool(submission.proof_path),
        "proof_original_name": submission.proof_original_name,
        "review_note": submission.review_note,
        "charge_label": (
            f"Installment {session.installment_number}"
            if session.installment_number
            else "Payment amount"
        ),
    }


@router.post("/{token}/receipt")
async def upload_bank_transfer_receipt(
    token: str,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    session_service = PaymentSessionService(db)
    session = session_service.get_active_session_by_token(token)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=session_service.describe_inactive_token(token),
        )
    if (getattr(session, "channel", None) or "") != CHANNEL_BANK_TRANSFER:
        raise HTTPException(status_code=400, detail="This payment link is not for bank transfer.")
    if session.status not in (SESSION_TERMS_ACCEPTED,):
        raise HTTPException(
            status_code=400,
            detail="Please accept the Terms and Conditions before uploading a receipt.",
        )

    data = await file.read()
    bt = BankTransferService(db, session_service.settings)
    submission = bt.get_by_session(session) or bt.enqueue_for_session(session)
    try:
        submission = bt.save_proof(
            submission,
            filename=file.filename or "receipt.jpg",
            content_type=file.content_type,
            data=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        await bt.notify_proof_submitted(submission)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Bank transfer Bitrix notify failed after upload submission_id=%s",
            submission.id,
        )

    return {
        "ok": True,
        "status": submission.status,
        "submission_id": submission.id,
        "message": (
            "Receipt uploaded. Finance will review it shortly. "
            "You can close this page."
        ),
    }
