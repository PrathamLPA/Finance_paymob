"""Add tabby_payment_id on payment_sessions for direct Tabby checkout."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_sessions",
        sa.Column("tabby_payment_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_payment_sessions_tabby_payment_id",
        "payment_sessions",
        ["tabby_payment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_sessions_tabby_payment_id", table_name="payment_sessions")
    op.drop_column("payment_sessions", "tabby_payment_id")
