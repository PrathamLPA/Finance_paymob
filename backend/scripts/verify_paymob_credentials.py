"""Check every configured Paymob credential against Paymob's own API.

    python scripts/verify_paymob_credentials.py
    python scripts/verify_paymob_credentials.py --transaction-id 26663925 --hmac 162583b7c1d962ec

With a transaction id it fetches the transaction as Paymob stored it and recomputes
the HMAC from those values, which distinguishes a wrong secret from a callback whose
signed field set differs from the documentation.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac as hmac_mod
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.integrations.paymob import iter_hmac_candidates  # noqa: E402


def mask(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 12:
        return f"{value[:2]}…{value[-2:]} (len {len(value)})"
    return f"{value[:8]}…{value[-4:]} (len {len(value)})"


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8] if value else "-"


def report_configuration(settings) -> None:
    print("== configured credentials ==")
    rows = [
        ("PAYMOB_BASE_URL", settings.paymob_base_url),
        ("PAYMOB_INTEGRATION_ID", str(settings.paymob_integration_id)),
        ("PAYMOB_PUBLIC_KEY", mask(settings.paymob_public_key)),
        ("PAYMOB_SECRET_KEY", mask(settings.paymob_secret_key)),
        ("PAYMOB_API_KEY", mask(settings.paymob_api_key)),
        (
            "PAYMOB_HMAC_SECRET",
            f"{mask(settings.paymob_hmac_secret)} fingerprint={fingerprint(settings.paymob_hmac_secret)}",
        ),
    ]
    for name, value in rows:
        print(f"  {name:<24} {value}")

    secret_mode = "test" if "_test_" in settings.paymob_secret_key else "live"
    public_mode = "test" if "_test_" in settings.paymob_public_key else "live"
    if secret_mode != public_mode:
        print(f"  WARNING secret key is {secret_mode} but public key is {public_mode}")
    else:
        print(f"  keys are {secret_mode} mode — the HMAC must be the {secret_mode}-mode value")
    print()


def auth_token(base: str, api_key: str) -> str | None:
    print("== API key check (POST /api/auth/tokens) ==")
    if not api_key:
        print("  SKIP no PAYMOB_API_KEY configured\n")
        return None
    response = httpx.post(f"{base}/api/auth/tokens", json={"api_key": api_key}, timeout=30.0)
    if response.is_error:
        print(f"  FAIL {response.status_code}: {response.text[:300]}\n")
        return None
    data = response.json()
    profile = data.get("profile") or {}
    print("  PASS api key accepted")
    print(f"    profile_id={profile.get('id')} active={profile.get('active')}")
    print(f"    company={profile.get('company_name')!r} country={profile.get('country')}\n")
    return data.get("token")


def fetch_transaction(base: str, token: str, transaction_id: str) -> dict | None:
    print(f"== transaction inquiry (GET /api/acceptance/transactions/{transaction_id}) ==")
    response = httpx.get(
        f"{base}/api/acceptance/transactions/{transaction_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if response.is_error:
        print(f"  FAIL {response.status_code}: {response.text[:300]}\n")
        return None
    obj = response.json()
    print("  PASS transaction retrieved")
    print(f"    success={obj.get('success')} pending={obj.get('pending')}")
    print(f"    amount_cents={obj.get('amount_cents')} currency={obj.get('currency')}")
    print(f"    created_at={obj.get('created_at')!r}")
    print(f"    integration_id={obj.get('integration_id')} owner={obj.get('owner')}\n")
    return obj


def compare_hmac(obj: dict, secret: str, received: str) -> None:
    print("== HMAC recomputation from Paymob's stored transaction ==")
    received = received.strip().lower()
    for label, concat in iter_hmac_candidates(obj):
        digest = hmac_mod.new(secret.encode(), concat.encode(), hashlib.sha512).hexdigest()
        if digest.startswith(received):
            print(f"  MATCH variant={label}")
            print(f"    concat={concat!r}\n")
            return
    print("  NO MATCH against any field-format variant")
    print("    the configured HMAC secret is not the key Paymob signed this callback with\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transaction-id", help="Transaction id from a callback log line")
    parser.add_argument("--hmac", help="Received signature, full or the logged prefix")
    args = parser.parse_args()

    settings = get_settings()
    base = settings.paymob_base_url.rstrip("/")
    report_configuration(settings)

    token = auth_token(base, settings.paymob_api_key)

    if args.transaction_id and token:
        obj = fetch_transaction(base, token, args.transaction_id)
        if obj and args.hmac and settings.paymob_hmac_secret:
            compare_hmac(obj, settings.paymob_hmac_secret, args.hmac)
        elif obj:
            print(json.dumps(obj, indent=2, default=str)[:4000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
