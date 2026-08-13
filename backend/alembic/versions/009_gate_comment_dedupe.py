"""Remember the last price-gate comment so it is not posted twice."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_workflows",
        sa.Column("last_gate_comment_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_workflows", "last_gate_comment_hash")
