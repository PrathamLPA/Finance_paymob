"""Database URL helpers for Supabase connectivity."""

import socket
from urllib.parse import urlparse, urlunparse


def resolve_supabase_url(database_url: str) -> str:
    """Use IPv6 literal when Supabase direct hostname fails on IPv4-only DNS."""
    parsed = urlparse(database_url)
    if not parsed.hostname or "supabase.co" not in parsed.hostname or "pooler" in parsed.hostname:
        return database_url

    try:
        socket.getaddrinfo(parsed.hostname, parsed.port or 5432, type=socket.SOCK_STREAM)
        return database_url
    except socket.gaierror:
        pass

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 5432, socket.AF_INET6, socket.SOCK_STREAM)
    except socket.gaierror:
        return database_url

    if not infos:
        return database_url

    ipv6 = infos[0][4][0]
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"

    port = parsed.port or 5432
    netloc = f"{auth}[{ipv6}]:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
