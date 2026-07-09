"""Resolve Supabase direct host to IPv6 for Windows/Python DNS issues."""

import socket
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings


def resolve_supabase_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.hostname or "supabase.co" not in parsed.hostname or "pooler" in parsed.hostname:
        return database_url

    try:
        socket.getaddrinfo(parsed.hostname, parsed.port or 5432, type=socket.SOCK_STREAM)
        return database_url
    except socket.gaierror:
        pass

    infos = socket.getaddrinfo(parsed.hostname, parsed.port or 5432, socket.AF_INET6, socket.SOCK_STREAM)
    if not infos:
        return database_url

    ipv6 = infos[0][4][0]
    netloc = f"{parsed.username}:{parsed.password}@[{ipv6}]:{parsed.port or 5432}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


if __name__ == "__main__":
    settings = get_settings()
    resolved = resolve_supabase_url(settings.database_url)
    print(resolved.split("@")[-1])
