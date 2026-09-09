"""Add collect_method to cash collections (cash vs POS desk payment)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cash_collections",
        sa.Column(
            "collect_method",
            sa.String(length=20),
            nullable=False,
            server_default="cash",
        ),
    )


def downgrade() -> None:
    op.drop_column("cash_collections", "collect_method")
