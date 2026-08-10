"""Customer-facing payment pages (proxies to backend API)."""

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.api_client import BackendApiError, accept_payment, get_payment

router = APIRouter(prefix="/payment", tags=["payment-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _form_context(
    request: Request,
    token: str,
    data: dict,
    *,
    error: str | None = None,
    course_for: str | None = None,
    registrant_name: str = "",
    registrant_email: str = "",
    registrant_phone: str = "",
) -> dict:
    return {
        "request": request,
        "token": token,
        "terms_version": data.get("terms_version", ""),
        "terms_html": data.get("terms_html", ""),
        "refund_policy_url": data.get("refund_policy_url", ""),
        "course_for": course_for,
        "registrant_name": registrant_name or "",
        "registrant_email": registrant_email or "",
        "registrant_phone": registrant_phone or "",
        "error": error,
    }


@router.get("/thank-you", response_class=HTMLResponse)
async def payment_thank_you(request: Request) -> HTMLResponse:
    """Paymob redirects here after checkout. UX only — webhook is source of truth."""
    params = request.query_params
    success_raw = (params.get("success") or params.get("txn_response_code") or "").lower()
    success = success_raw in ("true", "1", "approved", "00")
    failed = success_raw in ("false", "0") or (params.get("error_occured") or "").lower() in (
        "true",
        "1",
    )

    amount_cents = params.get("amount_cents") or params.get("amount")
    currency = (params.get("currency") or "AED").upper()
    amount_display = None
    if amount_cents and str(amount_cents).isdigit():
        amount_display = f"{int(amount_cents) / 100:.2f} {currency}"

    merchant_order_id = (
        params.get("merchant_order_id")
        or params.get("merchant_order")
        or params.get("order")
        or ""
    )

    if failed:
        heading = "Payment not completed"
        message = (
            "Paymob reported that this payment did not succeed. "
            "You can close this window and try again from your payment link."
        )
        page_title = "Payment Failed"
        footnote = "No amount was recorded in our system for a failed attempt."
    elif success:
        heading = "Payment submitted"
        message = (
            "Your card payment was submitted. We are confirming it with Paymob now — "
            "this usually takes a few seconds."
        )
        page_title = "Payment Submitted"
        footnote = (
            "Confirmation appears as a comment on your Bitrix lead once the Paymob webhook arrives."
        )
    else:
        heading = "Returning from Paymob"
        message = (
            "If you completed payment, we are confirming it now. "
            "If you cancelled, no charge was made."
        )
        page_title = "Payment Status"
        footnote = "Final status comes from the Paymob webhook, not this page."

    return templates.TemplateResponse(
        "thank_you.html",
        {
            "request": request,
            "page_title": page_title,
            "heading": heading,
            "message": message,
            "footnote": footnote,
            "amount_display": amount_display,
            "merchant_order_id": merchant_order_id,
        },
    )


@router.get("/{token}", response_class=HTMLResponse)
async def payment_terms_page(token: str, request: Request) -> HTMLResponse:
    try:
        data = await get_payment(token)
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=exc.status_code if exc.status_code in (404, 400) else 404,
        )

    return templates.TemplateResponse("terms.html", _form_context(request, token, data))


@router.post("/{token}/accept", response_model=None)
async def accept_terms_and_redirect(
    token: str,
    request: Request,
    accepted: str | None = Form(default=None),
    course_for: str | None = Form(default=None),
    registrant_name: str | None = Form(default=None),
    registrant_email: str | None = Form(default=None),
    registrant_phone: str | None = Form(default=None),
) -> Response:
    try:
        data = await get_payment(token)
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=404,
        )

    if accepted != "yes":
        return templates.TemplateResponse(
            "terms.html",
            _form_context(
                request,
                token,
                data,
                error="You must accept the Terms and Conditions to continue.",
                course_for=course_for,
                registrant_name=registrant_name or "",
                registrant_email=registrant_email or "",
                registrant_phone=registrant_phone or "",
            ),
            status_code=400,
        )

    try:
        result = await accept_payment(
            token,
            {
                "accepted": True,
                "course_for": course_for or "",
                "registrant_name": registrant_name or "",
                "registrant_email": registrant_email or "",
                "registrant_phone": registrant_phone or "",
            },
        )
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "terms.html",
            _form_context(
                request,
                token,
                data,
                error=exc.detail,
                course_for=course_for,
                registrant_name=registrant_name or "",
                registrant_email=registrant_email or "",
                registrant_phone=registrant_phone or "",
            ),
            status_code=exc.status_code if 400 <= exc.status_code < 500 else 400,
        )

    return RedirectResponse(url=result["checkout_url"], status_code=303)
