"""Customer-facing payment pages (proxies to backend API)."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.api_client import (
    BackendApiError,
    accept_payment,
    get_payment,
    get_receipt,
    lookup_payment_by_reference,
    upload_receipt,
)

router = APIRouter(prefix="/payment", tags=["payment-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _amount(data: dict, key: str) -> Decimal:
    try:
        return Decimal(str(data.get(key) or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_participants(raw: str | None) -> list[dict]:
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "name": str(item.get("name") or ""),
                "email": str(item.get("email") or ""),
                "product_id": int(item.get("product_id") or 0),
                "product_name": str(item.get("product_name") or ""),
            }
        )
    return cleaned


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
    payment_amount: str = "",
    participants: list[dict] | None = None,
) -> dict:
    remaining = _amount(data, "remaining_balance")
    minimum = _amount(data, "minimum_amount")
    payment_amount_value = _amount(data, "payment_amount") or remaining
    allows_partial = bool(data.get("allows_partial", False)) and minimum < remaining
    courses = data.get("courses") or []
    schedule = data.get("installment_schedule") or []
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
        "currency": data.get("currency", "AED"),
        "total_amount": f"{_amount(data, 'total_amount'):.2f}",
        "amount_paid": f"{_amount(data, 'amount_paid'):.2f}",
        "remaining_balance": f"{remaining:.2f}",
        "minimum_amount": f"{minimum:.2f}",
        "subtotal": f"{(_amount(data, 'subtotal') or _amount(data, 'total_amount')):.2f}",
        "vat_total": f"{_amount(data, 'vat_total'):.2f}",
        "tax_total": f"{_amount(data, 'tax_total'):.2f}",
        "balance_after_payment": f"{(_amount(data, 'balance_after_payment') if data.get('balance_after_payment') is not None else max(remaining - payment_amount_value, Decimal('0.00'))):.2f}",
        "allows_partial": allows_partial,
        "amount_locked": bool(data.get("amount_locked", True)),
        "charge_label": data.get("charge_label") or "Payment amount",
        "charge_source": data.get("charge_source") or "full",
        "installment_number": data.get("installment_number"),
        "installment_count": data.get("installment_count"),
        "installment_due_date": data.get("installment_due_date") or "",
        "installment_schedule": schedule,
        "pricing_lines": data.get("pricing_lines") or [],
        "payment_amount": payment_amount or f"{payment_amount_value:.2f}",
        "courses": courses,
        "courses_json": json.dumps(courses),
        "total_seats": int(data.get("total_seats") or 0),
        "participants_json": json.dumps(participants or []),
        "error": error,
        "channel": (data.get("channel") or "online"),
    }


@router.get("/thank-you", response_class=HTMLResponse)
async def payment_thank_you(request: Request) -> HTMLResponse:
    """Paymob redirects here after checkout; bank transfer after receipt upload."""
    params = request.query_params
    kind = (params.get("kind") or "").strip().lower()

    if kind == "bank_transfer":
        amount = (params.get("amount") or "").strip()
        currency = (params.get("currency") or "AED").upper()
        amount_display = f"{amount} {currency}" if amount else None
        name = (params.get("name") or "").strip()
        return templates.TemplateResponse(
            "thank_you.html",
            {
                "request": request,
                "page_title": "Receipt received",
                "heading": "Thank you - receipt received",
                "message": (
                    f"Hi {name}, we have received your bank transfer receipt. "
                    if name
                    else "We have received your bank transfer receipt. "
                )
                + "Our finance team will review it and get back to you shortly.",
                "footnote": (
                    "You can safely close this page. "
                    "If anything is unclear, your sales contact will reach out."
                ),
                "amount_display": amount_display,
                "customer_name": name,
                "merchant_order_id": "",
                "show_lms": False,
                "lms_url": None,
                "course_for": None,
                "auto_redirect_seconds": 0,
                "variant": "bank_transfer",
            },
        )

    if kind == "cash":
        amount = (params.get("amount") or "").strip()
        currency = (params.get("currency") or "AED").upper()
        amount_display = f"{amount} {currency}" if amount else None
        name = (params.get("name") or "").strip()
        return templates.TemplateResponse(
            "thank_you.html",
            {
                "request": request,
                "page_title": "Pay at the office desk",
                "heading": "Pay at the office desk",
                "message": "",
                "footnote": (
                    "You can close this page. Keep this screen or your name ready "
                    "when you reach the desk."
                ),
                "amount_display": amount_display,
                "customer_name": name,
                "merchant_order_id": "",
                "show_lms": False,
                "lms_url": None,
                "course_for": None,
                "auto_redirect_seconds": 0,
                "variant": "cash",
            },
        )

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
    # Paymob Intention often returns special_reference as merchant_order_id (WF-…).
    special_reference = (
        params.get("special_reference")
        or params.get("merchant_reference")
        or ""
    )
    lookup_ref = merchant_order_id if str(merchant_order_id).startswith("WF-") else special_reference
    if not lookup_ref and merchant_order_id:
        lookup_ref = str(merchant_order_id)

    show_lms = False
    lms_url = None
    course_for = None
    if lookup_ref and not failed:
        try:
            lookup = await lookup_payment_by_reference(str(lookup_ref))
            course_for = lookup.get("course_for")
            show_lms = bool(lookup.get("show_lms")) and (success or not failed)
            lms_url = lookup.get("lms_url")
        except BackendApiError:
            show_lms = False

    if failed:
        heading = "Payment not completed"
        message = (
            "Paymob reported that this payment did not succeed. "
            "You can close this window and try again from your payment link."
        )
        page_title = "Payment Failed"
        footnote = "No amount was recorded in our system for a failed attempt."
        variant = "failed"
    elif success:
        heading = "Payment submitted"
        message = (
            "Your card payment was submitted. We are confirming it with Paymob now - "
            "this usually takes a few seconds."
        )
        page_title = "Payment Submitted"
        footnote = (
            "Confirmation appears as a comment on your Bitrix lead once the Paymob webhook arrives."
        )
        variant = "success"
    else:
        heading = "Returning from Paymob"
        message = (
            "If you completed payment, we are confirming it now. "
            "If you cancelled, no charge was made."
        )
        page_title = "Payment Status"
        footnote = "Final status comes from the Paymob webhook, not this page."
        variant = "neutral"

    return templates.TemplateResponse(
        "thank_you.html",
        {
            "request": request,
            "page_title": page_title,
            "heading": heading,
            "message": message,
            "footnote": footnote,
            "amount_display": amount_display,
            "merchant_order_id": lookup_ref or merchant_order_id,
            "show_lms": show_lms,
            "lms_url": lms_url,
            "course_for": course_for,
            "auto_redirect_seconds": 5 if show_lms and success else 0,
            "variant": variant,
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

    # Bank transfer: after Terms, resume on receipt upload page
    if (
        data.get("channel") == "bank_transfer"
        and data.get("status") == "terms_accepted"
        and data.get("bank_transfer")
    ):
        return RedirectResponse(url=f"/payment/{token}/receipt", status_code=303)

    # Cash: after Terms, show office-desk thank you
    if data.get("channel") == "cash" and data.get("status") == "terms_accepted":
        from urllib.parse import urlencode

        qs = urlencode(
            {
                "kind": "cash",
                "amount": str(data.get("payment_amount") or ""),
                "currency": str(data.get("currency") or "AED"),
                "name": str(data.get("customer_name") or ""),
            }
        )
        return RedirectResponse(url=f"/payment/thank-you?{qs}", status_code=303)

    return templates.TemplateResponse("terms.html", _form_context(request, token, data))


@router.get("/{token}/receipt", response_class=HTMLResponse)
async def payment_receipt_page(token: str, request: Request) -> HTMLResponse:
    try:
        data = await get_receipt(token)
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=exc.status_code if exc.status_code in (404, 400) else 404,
        )
    # Already submitted - keep them on the receipt page so they can see status
    # and replace the file if needed (do not bounce to thank-you on every refresh).
    return templates.TemplateResponse(
        "receipt.html",
        {
            "request": request,
            "token": token,
            "error": None,
            "success": (
                "Receipt received. Finance will review it shortly."
                if data.get("status") == "pending_review" and data.get("has_proof")
                else None
            ),
            **data,
        },
    )


@router.post("/{token}/receipt", response_model=None)
async def payment_receipt_upload(token: str, request: Request) -> Response:
    form = await request.form()
    upload = form.get("receipt")
    try:
        data = await get_receipt(token)
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=404,
        )

    def _render(*, error: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            "receipt.html",
            {
                "request": request,
                "token": token,
                "error": error,
                "success": None,
                **data,
            },
            status_code=400 if error else 200,
        )

    if upload is None or not getattr(upload, "filename", None):
        return _render(error="Please choose a receipt photo or PDF to upload.")

    content = await upload.read()
    try:
        await upload_receipt(
            token,
            filename=str(upload.filename),
            content=content,
            content_type=getattr(upload, "content_type", None),
        )
    except BackendApiError as exc:
        return _render(error=exc.detail)

    from urllib.parse import urlencode

    qs = urlencode(
        {
            "kind": "bank_transfer",
            "amount": str(data.get("payment_amount") or ""),
            "currency": str(data.get("currency") or "AED"),
            "name": str(data.get("customer_name") or ""),
        }
    )
    return RedirectResponse(url=f"/payment/thank-you?{qs}", status_code=303)


@router.post("/{token}/accept", response_model=None)
async def accept_terms_and_redirect(
    token: str,
    request: Request,
    accepted: str | None = Form(default=None),
    course_for: str | None = Form(default=None),
    registrant_name: str | None = Form(default=None),
    registrant_email: str | None = Form(default=None),
    registrant_phone: str | None = Form(default=None),
    payment_amount: str | None = Form(default=None),
    participants_json: str | None = Form(default=None),
) -> Response:
    participants = _parse_participants(participants_json)

    async def _reject(message: str, status_code: int = 400) -> HTMLResponse:
        # Only load session context when we need to re-render the form (saves a
        # round-trip on the happy path, which matters for cash confirm lag).
        try:
            data = await get_payment(token)
        except BackendApiError as exc:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": exc.detail},
                status_code=404,
            )
        return templates.TemplateResponse(
            "terms.html",
            _form_context(
                request,
                token,
                data,
                error=message,
                course_for=course_for,
                registrant_name=registrant_name or "",
                registrant_email=registrant_email or "",
                registrant_phone=registrant_phone or "",
                payment_amount=payment_amount or "",
                participants=participants,
            ),
            status_code=status_code,
        )

    if accepted != "yes":
        return await _reject("You must accept the Terms and Conditions to continue.")

    chosen_amount: Decimal | None = None
    if payment_amount and payment_amount.strip():
        try:
            chosen_amount = Decimal(payment_amount.strip())
        except InvalidOperation:
            return await _reject("Please enter a valid payment amount.")

    try:
        result = await accept_payment(
            token,
            {
                "accepted": True,
                "course_for": course_for or "",
                "registrant_name": registrant_name or "",
                "registrant_email": registrant_email or "",
                "registrant_phone": registrant_phone or "",
                "payment_amount": str(chosen_amount) if chosen_amount is not None else None,
                "participants": participants,
            },
        )
    except BackendApiError as exc:
        return await _reject(
            exc.detail, exc.status_code if 400 <= exc.status_code < 500 else 400
        )

    return RedirectResponse(url=result["checkout_url"], status_code=303)
