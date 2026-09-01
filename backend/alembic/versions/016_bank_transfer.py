"""Bank transfer submissions + payment_sessions.channel."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_sessions",
        sa.Column(
            "channel",
            sa.String(30),
            nullable=False,
            server_default="online",
        ),
    )
    op.create_index("ix_payment_sessions_channel", "payment_sessions", ["channel"])

    op.create_table(
        "bank_transfer_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("customer_workflows.id"),
            nullable=False,
        ),
        sa.Column(
            "payment_session_id",
            sa.Integer(),
            sa.ForeignKey("payment_sessions.id"),
            nullable=True,
        ),
        sa.Column("bitrix_lead_id", sa.Integer(), nullable=False),
        sa.Column("bitrix_estimate_id", sa.Integer(), nullable=True),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("course_title", sa.String(500), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("due_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="AED"),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="awaiting_upload",
        ),
        sa.Column("proof_path", sa.Text(), nullable=True),
        sa.Column("proof_content_type", sa.String(120), nullable=True),
        sa.Column("proof_original_name", sa.String(255), nullable=True),
        sa.Column(
            "reviewed_by_id",
            sa.Integer(),
            sa.ForeignKey("staff_users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("bitrix_lead_comment_id", sa.Integer(), nullable=True),
        sa.Column("bitrix_estimate_comment_id", sa.Integer(), nullable=True),
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
            name="uq_bank_transfer_workflow_installment",
        ),
    )
    op.create_index(
        "ix_bank_transfer_submissions_workflow_id",
        "bank_transfer_submissions",
        ["workflow_id"],
    )
    op.create_index(
        "ix_bank_transfer_submissions_payment_session_id",
        "bank_transfer_submissions",
        ["payment_session_id"],
    )
    op.create_index(
        "ix_bank_transfer_submissions_bitrix_lead_id",
        "bank_transfer_submissions",
        ["bitrix_lead_id"],
    )
    op.create_index(
        "ix_bank_transfer_submissions_status",
        "bank_transfer_submissions",
        ["status"],
    )
    op.create_index(
        "ix_bank_transfer_submissions_reviewed_by_id",
        "bank_transfer_submissions",
        ["reviewed_by_id"],
    )


def downgrade() -> None:
    op.drop_table("bank_transfer_submissions")
    op.drop_index("ix_payment_sessions_channel", table_name="payment_sessions")
    op.drop_column("payment_sessions", "channel")
