"""One shared HTTP client per event loop, so Bitrix and Zoho calls reuse connections.

Opening a fresh client for every call repeats the DNS lookup and TLS handshake each
time. A single payment approval makes a dozen calls, so that setup cost added up to
seconds. Connections are kept alive for a short time (shorter than the servers' own
idle timeout) so a reused connection is rarely one the server already closed.
"""

from __future__ import annotations

import asyncio
import httpx

_clients: dict[int, httpx.AsyncClient] = {}

# Errors that mean "that reused connection was already dead" and are safe to retry once.
STALE_CONNECTION_ERRORS: tuple[type[Exception], ...] = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
)


def shared_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=20.0,
            ),
            http2=False,
        )
        _clients[loop_id] = client
    return client
