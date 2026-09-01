"""Dedupe Paymob link-failure Bitrix notifications per lead + email."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_workflows",
        sa.Column("last_paymob_failure_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_workflows", "last_paymob_failure_hash")
