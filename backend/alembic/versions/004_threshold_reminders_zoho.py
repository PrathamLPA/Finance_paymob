"""Add threshold, reminders, and Zoho customer fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer_workflows", sa.Column("zoho_customer_id", sa.String(length=100), nullable=True))
    op.add_column(
        "customer_workflows",
        sa.Column("payment_status", sa.String(length=50), nullable=False, server_default="pending"),
    )
    op.add_column("customer_workflows", sa.Column("threshold_met_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "customer_workflows",
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("customer_workflows", sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "customer_workflows",
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("customer_workflows", "reminder_count")
    op.drop_column("customer_workflows", "last_reminder_at")
    op.drop_column("customer_workflows", "reminders_enabled")
    op.drop_column("customer_workflows", "threshold_met_at")
    op.drop_column("customer_workflows", "payment_status")
    op.drop_column("customer_workflows", "zoho_customer_id")
