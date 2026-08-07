"""Store the complete Bitrix lead snapshot at payment stage."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_workflows",
        sa.Column("bitrix_lead_stage_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "customer_workflows",
        sa.Column("bitrix_lead_payload", sa.JSON(), nullable=True),
    )
    op.add_column(
        "customer_workflows",
        sa.Column("lead_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_workflows", "lead_synced_at")
    op.drop_column("customer_workflows", "bitrix_lead_payload")
    op.drop_column("customer_workflows", "bitrix_lead_stage_id")
