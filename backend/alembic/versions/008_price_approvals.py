"""Pending manager approvals for under-catalog selling prices."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "price_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("bitrix_lead_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("total_payable", sa.String(length=32), nullable=False),
        sa.Column("catalog_minimum_total", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("lines_payload", sa.JSON(), nullable=False),
        sa.Column("lead_title", sa.String(length=255), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("owner_name", sa.String(length=255), nullable=True),
        sa.Column("manager_user_id", sa.Integer(), nullable=True),
        sa.Column("manager_email", sa.String(length=320), nullable=True),
        sa.Column("manager_name", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["workflow_id"], ["customer_workflows.id"]),
    )
    op.create_index("ix_price_approvals_workflow_id", "price_approvals", ["workflow_id"])
    op.create_index("ix_price_approvals_bitrix_lead_id", "price_approvals", ["bitrix_lead_id"])
    op.create_index("ix_price_approvals_token", "price_approvals", ["token"], unique=True)
    op.create_index("ix_price_approvals_status", "price_approvals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_price_approvals_status", table_name="price_approvals")
    op.drop_index("ix_price_approvals_token", table_name="price_approvals")
    op.drop_index("ix_price_approvals_bitrix_lead_id", table_name="price_approvals")
    op.drop_index("ix_price_approvals_workflow_id", table_name="price_approvals")
    op.drop_table("price_approvals")
