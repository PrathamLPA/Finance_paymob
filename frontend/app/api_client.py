"""HTTP client helpers for calling the backend payment API."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class BackendApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def get_payment(token: str) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.api_base_url.rstrip('/')}/api/payment/{token}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        detail = _extract_detail(response)
        raise BackendApiError(response.status_code, detail)
    return response.json()


async def accept_payment(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.api_base_url.rstrip('/')}/api/payment/{token}/accept"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload)
    if response.status_code >= 400:
        detail = _extract_detail(response)
        raise BackendApiError(response.status_code, detail)
    return response.json()


def _extract_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        detail = data.get("detail", response.text)
        if isinstance(detail, list):
            return "; ".join(str(item) for item in detail)
        return str(detail)
    except Exception:
        return response.text or "Request failed"
