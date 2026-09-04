"""HTTP client helpers for calling the backend payment API."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("frontend.api")

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class BackendApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def _request(
    method: str,
    path: str,
    *,
    timeout: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.api_base_url.rstrip('/')}{path}"
    client = get_http_client()
    started = time.perf_counter()
    try:
        response = await client.request(method, url, timeout=timeout, **kwargs)
    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(
            "BACKEND TIMEOUT %s %s after %sms",
            method,
            path,
            elapsed_ms,
        )
        raise BackendApiError(504, f"Backend timed out after {elapsed_ms}ms") from exc
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(
            "BACKEND HTTP ERROR %s %s after %sms | %s",
            method,
            path,
            elapsed_ms,
            exc,
        )
        raise BackendApiError(502, f"Backend unreachable: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        detail = _extract_detail(response)
        logger.warning(
            "BACKEND %s %s -> %s in %sms | detail=%s",
            method,
            path,
            response.status_code,
            elapsed_ms,
            detail[:300],
        )
        raise BackendApiError(response.status_code, detail)

    logger.info(
        "BACKEND %s %s -> %s in %sms",
        method,
        path,
        response.status_code,
        elapsed_ms,
    )
    if not response.content:
        return {}
    return response.json()


async def get_payment(token: str) -> dict[str, Any]:
    return await _request("GET", f"/api/payment/{token}", timeout=30.0)


async def lookup_payment_by_reference(merchant_reference: str) -> dict[str, Any]:
    return await _request(
        "GET",
        f"/api/payment/lookup/{merchant_reference}",
        timeout=15.0,
    )


async def accept_payment(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await _request(
        "POST",
        f"/api/payment/{token}/accept",
        json=payload,
        timeout=45.0,
    )


async def get_receipt(token: str) -> dict[str, Any]:
    return await _request("GET", f"/api/payment/{token}/receipt", timeout=30.0)


async def upload_receipt(
    token: str,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
) -> dict[str, Any]:
    files = {"file": (filename, content, content_type or "application/octet-stream")}
    return await _request(
        "POST",
        f"/api/payment/{token}/receipt",
        files=files,
        timeout=60.0,
    )


async def get_approval(token: str) -> dict[str, Any]:
    return await _request("GET", f"/api/approvals/{token}", timeout=30.0)


async def decide_approval(
    token: str,
    *,
    approve: bool,
    note: str = "",
    product_prices: list[dict] | None = None,
    installments: list[dict] | None = None,
    rejected_case: str | None = None,
) -> dict[str, Any]:
    action = "approve" if approve else "reject"
    payload: dict[str, Any] = {"note": note}
    if product_prices is not None:
        payload["product_prices"] = product_prices
    if installments is not None:
        payload["installments"] = installments
    if rejected_case:
        payload["rejected_case"] = rejected_case
    return await _request(
        "POST",
        f"/api/approvals/{token}/{action}",
        json=payload,
        timeout=60.0,
    )


def _extract_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        detail = data.get("detail", response.text)
        if isinstance(detail, list):
            return "; ".join(str(item) for item in detail)
        return str(detail)
    except Exception:
        return response.text or "Request failed"
