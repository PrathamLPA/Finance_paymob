"""JSON payment APIs consumed by the separate frontend service."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.payment_session_service import PaymentSessionService
from app.services.terms_service import TermsService

router = APIRouter(prefix="/api/payment", tags=["payment-api"])


class AcceptTermsBody(BaseModel):
    accepted: bool = False
    course_for: str = ""
    registrant_name: str = ""
    registrant_email: str = ""
    registrant_phone: str = ""


@router.get("/{token}")
async def get_payment_session(token: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session_service = PaymentSessionService(db)
    session = session_service.get_active_session_by_token(token)
    if not session:
        raise HTTPException(status_code=404, detail="This payment link is invalid or has expired.")

    terms_service = TermsService(db)
    context = terms_service.get_terms_context()
    return {
        "token": token,
        "status": session.status,
        "terms_version": context["terms_version"],
        "terms_html": context["terms_html"],
        "refund_policy_url": context["refund_policy_url"],
    }


@router.post("/{token}/accept")
async def accept_payment_terms(
    token: str,
    request: Request,
    body: AcceptTermsBody,
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
    )
    return {"checkout_url": checkout_url}
