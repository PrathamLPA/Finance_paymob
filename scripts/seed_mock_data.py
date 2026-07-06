"""CLI: seed mock Paymob-shaped data into DATABASE_URL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.seed_mock_data import seed_mock_data

if __name__ == "__main__":
    db = SessionLocal()
    try:
        result = seed_mock_data(db)
        print(f"Seeded {result['count']} mock customers:")
        for c in result["customers"]:
            print(f"  - {c['name']} ({c['email']})")
            print(f"    Paid: {c['amount_paid']} AED | Remaining: {c['remaining']} AED")
            print(f"    Payment URL: {c['payment_url']}")
    finally:
        db.close()
