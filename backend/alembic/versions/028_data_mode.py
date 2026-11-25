"""Stamp payment records as test or live data."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "customer_workflows",
    "payment_sessions",
    "payment_transactions",
    "cash_collections",
    "cash_deposits",
    "bank_transfer_submissions",
    "finance_verifications",
    "email_logs",
)


def upgrade() -> None:
    # Everything that exists today was created while developing, so it becomes test data.
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("data_mode", sa.String(10), nullable=False, server_default="test"),
        )
        op.create_index(f"ix_{table}_data_mode", table, ["data_mode"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_data_mode", table_name=table)
        op.drop_column(table, "data_mode")
