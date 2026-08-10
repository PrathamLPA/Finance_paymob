"""Check a candidate Paymob HMAC secret against a real failed callback.

Copy the transaction JSON from the "Paymob HMAC transaction dump" log line and the
received signature from the "received=" field, then try one or more candidate
secrets from the Paymob dashboard:

    python scripts/check_paymob_hmac.py --transaction txn.json \
        --hmac 162583b7c1d962ec CANDIDATE_SECRET_A CANDIDATE_SECRET_B

The received signature may be the truncated prefix shown in the log.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.paymob import (  # noqa: E402
    extract_transaction_obj,
    iter_hmac_candidates,
    missing_transaction_hmac_fields,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transaction",
        required=True,
        type=Path,
        help="File holding the transaction JSON from the log dump",
    )
    parser.add_argument(
        "--hmac",
        required=True,
        help="Received signature, full or the prefix shown in the log",
    )
    parser.add_argument("secrets", nargs="+", help="Candidate HMAC secrets to test")
    args = parser.parse_args()

    payload = json.loads(args.transaction.read_text(encoding="utf-8"))
    obj = extract_transaction_obj(payload)
    received = args.hmac.strip().lower()

    missing = missing_transaction_hmac_fields(obj)
    if missing:
        print(f"warning: transaction is missing HMAC fields: {', '.join(missing)}")

    variants = list(iter_hmac_candidates(obj))
    print(f"transaction {obj.get('id')}: testing {len(args.secrets)} secret(s) "
          f"against {len(variants)} field-format variant(s)\n")

    for secret in args.secrets:
        fingerprint = hashlib.sha256(secret.encode()).hexdigest()[:8]
        for label, concat in variants:
            digest = hmac.new(secret.encode(), concat.encode(), hashlib.sha512).hexdigest()
            if digest.startswith(received):
                print(f"MATCH  fingerprint={fingerprint} variant={label}")
                return 0
        print(f"no match  fingerprint={fingerprint} (len {len(secret)})")

    print("\nNone of the candidate secrets produced the received signature.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
