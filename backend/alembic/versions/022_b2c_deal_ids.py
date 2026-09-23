"""Add b2c_deal_ids JSON list for per-course B2C Ops cards."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_workflows",
        sa.Column("b2c_deal_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_workflows", "b2c_deal_ids")
