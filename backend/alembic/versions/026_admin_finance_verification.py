"""Developer admin flag and finance-manager verification queue."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_table(
        "finance_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payment_transaction_id",
            sa.Integer(),
            sa.ForeignKey("payment_transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("customer_workflows.id"),
            nullable=False,
        ),
        sa.Column("bitrix_lead_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("channel", sa.String(50), nullable=True),
        sa.Column("amount", sa.String(32), nullable=False, server_default="0.00"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="AED"),
        sa.Column("comment_prefix", sa.Text(), nullable=False, server_default="Payment successful"),
        sa.Column("skip_zoho", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("skip_deals", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint("payment_transaction_id", name="uq_finance_verifications_txn"),
    )
    op.create_index(
        "ix_finance_verifications_status", "finance_verifications", ["status"]
    )
    op.create_index(
        "ix_finance_verifications_workflow_id", "finance_verifications", ["workflow_id"]
    )
    op.create_index(
        "ix_finance_verifications_lead", "finance_verifications", ["bitrix_lead_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_finance_verifications_lead", table_name="finance_verifications")
    op.drop_index("ix_finance_verifications_workflow_id", table_name="finance_verifications")
    op.drop_index("ix_finance_verifications_status", table_name="finance_verifications")
    op.drop_table("finance_verifications")
    op.drop_table("app_settings")
