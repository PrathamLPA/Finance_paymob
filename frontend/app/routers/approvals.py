"""Manager discount approval pages."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api_client import BackendApiError, decide_approval, get_approval

router = APIRouter(prefix="/approvals", tags=["approvals-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/{token}", response_class=HTMLResponse)
async def approval_page(token: str, request: Request) -> HTMLResponse:
    try:
        data = await get_approval(token)
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=exc.status_code if exc.status_code in (404, 400) else 404,
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
) -> HTMLResponse:
    try:
        data = await get_approval(token)
    except BackendApiError as exc:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": exc.detail},
            status_code=404,
        )

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

    try:
        result = await decide_approval(
            token,
            approve=approve,
            note=note,
            product_prices=product_prices if approve else [],
            installments=installments if approve else [],
        )
        data = await get_approval(token)
    except BackendApiError as exc:
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
