"""Customer-facing payment and T&C routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.payment_session_service import PaymentSessionService
from app.services.terms_service import TermsService

router = APIRouter(prefix="/payment", tags=["payment"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/thank-you", response_class=HTMLResponse)
async def payment_thank_you(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "thank_you.html",
        {"request": request},
    )


@router.get("/{token}", response_class=HTMLResponse)
async def payment_terms_page(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    session_service = PaymentSessionService(db)
    session = session_service.get_active_session_by_token(token)

    terms_service = TermsService(db)
    context = terms_service.get_terms_context()
    context["token"] = token
    context["request"] = request

    if not session:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "message": "This payment link is invalid or has expired.",
            },
            status_code=404,
        )

    return templates.TemplateResponse("terms.html", context)


@router.post("/{token}/accept", response_model=None)
async def accept_terms_and_redirect(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    accepted: str | None = Form(default=None),
) -> Response:
    terms_service = TermsService(db)

    if accepted != "yes":
        context = terms_service.get_terms_context()
        context["token"] = token
        context["request"] = request
        context["error"] = "You must accept the Terms and Conditions to continue."
        return templates.TemplateResponse("terms.html", context, status_code=400)

    client_ip = request.client.host if request.client else None
    checkout_url = await terms_service.accept_terms(token, accepted=True, ip_address=client_ip)
    return RedirectResponse(url=checkout_url, status_code=303)
