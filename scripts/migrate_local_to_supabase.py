"""Copy data from local Docker Postgres to DATABASE_URL (Supabase)."""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

LOCAL_URL = "postgresql+psycopg://finance:finance@localhost:5432/finance_automation"

TABLES = [
    "customer_workflows",
    "payment_sessions",
    "payment_transactions",
    "terms_acceptances",
]

SEQUENCES = [
    "customer_workflows_id_seq",
    "payment_sessions_id_seq",
    "payment_transactions_id_seq",
    "terms_acceptances_id_seq",
]


def copy_table(local_conn, remote_conn, table: str) -> int:
    rows = local_conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
    if not rows:
        return 0

    remote_conn.execute(text(f"DELETE FROM {table}"))
    columns = rows[0].keys()
    col_list = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    insert_sql = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})")

    for row in rows:
        remote_conn.execute(insert_sql, dict(row))

    return len(rows)


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    remote_url = settings.database_url

    print(f"Source: local Docker ({LOCAL_URL.split('@')[-1]})")
    print(f"Target: {remote_url.split('@')[-1]}")

    local_engine = create_engine(LOCAL_URL)
    remote_engine = create_engine(remote_url, connect_args={"connect_timeout": 15})

    with local_engine.connect() as local_conn, remote_engine.begin() as remote_conn:
        for table in TABLES:
            try:
                count = copy_table(local_conn, remote_conn, table)
                print(f"  {table}: {count} rows")
            except Exception as exc:
                if "does not exist" in str(exc).lower():
                    print(f"  {table}: skipped (not in source)")
                else:
                    raise

        for seq in SEQUENCES:
            try:
                remote_conn.execute(
                    text(
                        f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {seq.replace('_id_seq', '')}), 1))"
                    )
                )
            except Exception:
                pass

    print("Data migration complete.")


if __name__ == "__main__":
    main()
