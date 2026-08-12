"""Store Bitrix estimate id on the customer workflow."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_workflows",
        sa.Column("bitrix_estimate_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_customer_workflows_bitrix_estimate_id",
        "customer_workflows",
        ["bitrix_estimate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_workflows_bitrix_estimate_id", table_name="customer_workflows")
    op.drop_column("customer_workflows", "bitrix_estimate_id")
