"""Remember each payment's follow-up progress so it can resume after a failure or restart."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_transactions", sa.Column("post_state", sa.String(12), nullable=False, server_default=""))
    op.add_column("payment_transactions", sa.Column("post_steps", sa.JSON(), nullable=True))
    op.add_column("payment_transactions", sa.Column("post_problems", sa.JSON(), nullable=True))
    op.add_column("payment_transactions", sa.Column("post_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payment_transactions", sa.Column("post_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_payment_transactions_post_state", "payment_transactions", ["post_state"])


def downgrade() -> None:
    op.drop_index("ix_payment_transactions_post_state", table_name="payment_transactions")
    for col in ("post_updated_at", "post_attempts", "post_problems", "post_steps", "post_state"):
        op.drop_column("payment_transactions", col)
