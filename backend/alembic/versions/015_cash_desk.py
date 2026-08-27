"""Cash desk: staff users, cash collections, cash deposits."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="employee"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_staff_users_email"),
    )
    op.create_index("ix_staff_users_email", "staff_users", ["email"])
    op.create_index("ix_staff_users_role", "staff_users", ["role"])

    op.create_table(
        "cash_collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("customer_workflows.id"), nullable=False),
        sa.Column("bitrix_lead_id", sa.Integer(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("course_title", sa.String(500), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("due_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "collected_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("currency", sa.String(10), nullable=False, server_default="AED"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("claimed_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "installment_number",
            name="uq_cash_collection_workflow_installment",
        ),
    )
    op.create_index("ix_cash_collections_workflow_id", "cash_collections", ["workflow_id"])
    op.create_index("ix_cash_collections_bitrix_lead_id", "cash_collections", ["bitrix_lead_id"])
    op.create_index("ix_cash_collections_status", "cash_collections", ["status"])
    op.create_index("ix_cash_collections_claimed_by_id", "cash_collections", ["claimed_by_id"])
    op.create_index("ix_cash_collections_collected_by_id", "cash_collections", ["collected_by_id"])

    op.create_table(
        "cash_deposits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="AED"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "deposited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index("ix_cash_deposits_employee_id", "cash_deposits", ["employee_id"])
    op.create_index("ix_cash_deposits_recorded_by_id", "cash_deposits", ["recorded_by_id"])


def downgrade() -> None:
    op.drop_table("cash_deposits")
    op.drop_table("cash_collections")
    op.drop_table("staff_users")
