"""Manager discount approval pages."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api_client import BackendApiError, decide_approval, get_approval

router = APIRouter(prefix="/approvals", tags=["approvals-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
logger = logging.getLogger("frontend.approvals")


@router.get("/{token}", response_class=HTMLResponse)
async def approval_page(token: str, request: Request) -> HTMLResponse:
    started = time.perf_counter()
    try:
        data = await get_approval(token)
    except BackendApiError as exc:
        logger.warning(
            "approval page load failed | token=%s... status=%s detail=%s",
            token[:8],
            exc.status_code,
            exc.detail[:200],
        )
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=exc.status_code if exc.status_code in (404, 400) else 404,
        )
    logger.info(
        "approval page loaded | token=%s... status=%s in %sms",
        token[:8],
        data.get("status"),
        int((time.perf_counter() - started) * 1000),
    )
    return templates.TemplateResponse(
        "approval.html",
        {"request": request, "token": token, "data": data, "error": None, "result": None},
    )


@router.post("/{token}/decide", response_class=HTMLResponse)
async def approval_decide(
    token: str,
    request: Request,
    decision: str = Form(...),
    note: str = Form(default=""),
    overrides_json: str = Form(default="{}"),
    rejected_case: str = Form(default=""),
) -> HTMLResponse:
    """Decide without a pre-fetch get_approval (cuts one backend round-trip)."""
    started = time.perf_counter()
    approve = decision.strip().lower() == "approve"
    product_prices: list[dict] = []
    installments: list[dict] = []
    try:
        overrides = json.loads(overrides_json or "{}")
        if isinstance(overrides, dict):
            product_prices = list(overrides.get("product_prices") or [])
            installments = list(overrides.get("installments") or [])
    except json.JSONDecodeError:
        overrides = {}

    logger.info(
        "approval decide start | token=%s... decision=%s products=%s installments=%s",
        token[:8],
        "approve" if approve else "reject",
        len(product_prices),
        len(installments),
    )

    try:
        decide_started = time.perf_counter()
        result = await decide_approval(
            token,
            approve=approve,
            note=note,
            product_prices=product_prices,
            installments=installments,
            rejected_case=(rejected_case or None) if not approve else None,
        )
        decide_ms = int((time.perf_counter() - decide_started) * 1000)
        # One refresh after decide so the page shows final status / summary.
        refresh_started = time.perf_counter()
        data = await get_approval(token)
        refresh_ms = int((time.perf_counter() - refresh_started) * 1000)
    except BackendApiError as exc:
        logger.warning(
            "approval decide failed | token=%s... status=%s detail=%s total=%sms",
            token[:8],
            exc.status_code,
            exc.detail[:200],
            int((time.perf_counter() - started) * 1000),
        )
        try:
            data = await get_approval(token)
        except BackendApiError:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": exc.detail},
                status_code=404,
            )
        return templates.TemplateResponse(
            "approval.html",
            {
                "request": request,
                "token": token,
                "data": data,
                "error": exc.detail,
                "result": None,
            },
            status_code=400,
        )

    total_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "approval decide ok | token=%s... result=%s decide=%sms refresh=%sms total=%sms",
        token[:8],
        result.get("status"),
        decide_ms,
        refresh_ms,
        total_ms,
    )
    return templates.TemplateResponse(
        "approval.html",
        {
            "request": request,
            "token": token,
            "data": data,
            "error": None,
            "result": result,
        },
    )
