"""Register Tabby payment webhook once (test or live key).

Usage (from backend/ with env loaded):

  python -m scripts.register_tabby_webhook

Requires: TABBY_SECRET_KEY, TABBY_MERCHANT_CODE, TABBY_WEBHOOK_AUTH_VALUE,
PUBLIC_BASE_URL (or pass --url).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Register Tabby payment webhook")
    parser.add_argument(
        "--url",
        default="",
        help="Webhook URL (default: {PUBLIC_BASE_URL}/webhooks/tabby)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TABBY_BASE_URL", "https://api.tabby.ai"),
        help="Tabby API base URL",
    )
    args = parser.parse_args()

    secret = (os.environ.get("TABBY_SECRET_KEY") or "").strip()
    merchant = (os.environ.get("TABBY_MERCHANT_CODE") or "").strip()
    auth_value = (os.environ.get("TABBY_WEBHOOK_AUTH_VALUE") or "").strip()
    auth_header = (
        os.environ.get("TABBY_WEBHOOK_AUTH_HEADER") or "X-Tabby-Auth"
    ).strip()
    public = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    webhook_url = (args.url or "").strip() or (
        f"{public}/webhooks/tabby" if public else ""
    )

    missing = [
        name
        for name, val in (
            ("TABBY_SECRET_KEY", secret),
            ("TABBY_MERCHANT_CODE", merchant),
            ("TABBY_WEBHOOK_AUTH_VALUE", auth_value),
            ("webhook url", webhook_url),
        )
        if not val
    ]
    if missing:
        print("Missing:", ", ".join(missing), file=sys.stderr)
        return 1

    endpoint = f"{args.base_url.rstrip('/')}/api/v1/webhooks"
    payload = {
        "url": webhook_url,
        "header": {"title": auth_header, "value": auth_value},
    }
    headers = {
        "Authorization": f"Bearer {secret}",
        "X-Merchant-Code": merchant,
        "Content-Type": "application/json",
    }
    print(f"POST {endpoint}")
    print(json.dumps(payload, indent=2))
    response = httpx.post(endpoint, headers=headers, json=payload, timeout=30.0)
    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)
    return 0 if response.status_code < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
