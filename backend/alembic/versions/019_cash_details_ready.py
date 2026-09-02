"""Cash collection customer details / terms gate fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cash_collections",
        sa.Column("payment_session_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "cash_collections",
        sa.Column("details_ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cash_collections_payment_session_id",
        "cash_collections",
        "payment_sessions",
        ["payment_session_id"],
        ["id"],
    )
    op.create_index(
        "ix_cash_collections_payment_session_id",
        "cash_collections",
        ["payment_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cash_collections_payment_session_id", table_name="cash_collections")
    op.drop_constraint(
        "fk_cash_collections_payment_session_id",
        "cash_collections",
        type_="foreignkey",
    )
    op.drop_column("cash_collections", "details_ready_at")
    op.drop_column("cash_collections", "payment_session_id")
