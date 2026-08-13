"""Track whether a price approval actually reached the manager."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "price_approvals",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "price_approvals",
        sa.Column("notified_via", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_approvals", "notified_via")
    op.drop_column("price_approvals", "notified_at")
