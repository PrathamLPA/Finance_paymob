"""Persist installment schedule and pricing snapshot for first payment."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_workflows",
        sa.Column("pricing_snapshot", sa.JSON(), nullable=True),
    )
    op.add_column(
        "payment_sessions",
        sa.Column("installment_number", sa.Integer(), nullable=True),
    )
    op.create_table(
        "workflow_installments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("customer_workflows.id"), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "installment_number",
            name="uq_workflow_installment_number",
        ),
    )
    op.create_index(
        "ix_workflow_installments_workflow_id",
        "workflow_installments",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_installments_workflow_id", table_name="workflow_installments")
    op.drop_table("workflow_installments")
    op.drop_column("payment_sessions", "installment_number")
    op.drop_column("customer_workflows", "pricing_snapshot")
