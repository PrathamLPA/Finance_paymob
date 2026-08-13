"""Store how a payment session charge amount was chosen."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_sessions",
        sa.Column("charge_source", sa.String(length=40), nullable=False, server_default="full"),
    )
    op.add_column(
        "payment_sessions",
        sa.Column("amount_locked", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("payment_sessions", "amount_locked")
    op.drop_column("payment_sessions", "charge_source")
