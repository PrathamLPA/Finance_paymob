"""Customer-chosen payment mode on payment sessions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_sessions",
        sa.Column("customer_payment_mode", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_sessions", "customer_payment_mode")
