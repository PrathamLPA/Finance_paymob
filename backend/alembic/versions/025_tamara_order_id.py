"""Add tamara_order_id on payment_sessions for direct Tamara checkout."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_sessions",
        sa.Column("tamara_order_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_payment_sessions_tamara_order_id",
        "payment_sessions",
        ["tamara_order_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_sessions_tamara_order_id", table_name="payment_sessions")
    op.drop_column("payment_sessions", "tamara_order_id")
