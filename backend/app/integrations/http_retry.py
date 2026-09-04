"""Shared httpx transport helpers (timeouts + one reconnect retry)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE = (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout)


async def request_with_retry(
    method: str,
    url: str,
    *,
    timeout: float | httpx.Timeout = 30.0,
    retries: int = 1,
    label: str = "HTTP",
    **kwargs: Any,
) -> httpx.Response:
    """POST/GET/etc with one transport retry (Railway blips), like Bitrix."""
    last_exc: Exception | None = None
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.request(method, url, **kwargs)
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                logger.warning(
                    "%s transport blip (%s) on %s %s; retrying",
                    label,
                    type(exc).__name__,
                    method,
                    url,
                )
                continue
            raise
    raise last_exc or RuntimeError(f"{label} request failed")
