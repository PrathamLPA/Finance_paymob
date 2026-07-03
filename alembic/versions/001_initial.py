"""Initial schema."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_workflows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bitrix_lead_id", sa.Integer(), nullable=False),
        sa.Column("sales_deal_id", sa.Integer(), nullable=True),
        sa.Column("finance_deal_id", sa.Integer(), nullable=True),
        sa.Column("b2c_deal_id", sa.Integer(), nullable=True),
        sa.Column("customer_email", sa.String(length=320), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("zoho_invoice_id", sa.String(length=100), nullable=True),
        sa.Column("first_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bitrix_lead_id"),
    )
    op.create_index("ix_customer_workflows_bitrix_lead_id", "customer_workflows", ["bitrix_lead_id"])
    op.create_index("ix_customer_workflows_sales_deal_id", "customer_workflows", ["sales_deal_id"])
    op.create_index("ix_customer_workflows_finance_deal_id", "customer_workflows", ["finance_deal_id"])
    op.create_index("ix_customer_workflows_b2c_deal_id", "customer_workflows", ["b2c_deal_id"])

    op.create_table(
        "payment_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("charge_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("paymob_session_id", sa.String(length=100), nullable=True),
        sa.Column("paymob_checkout_url", sa.Text(), nullable=True),
        sa.Column("merchant_reference", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["customer_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_payment_sessions_workflow_id", "payment_sessions", ["workflow_id"])
    op.create_index("ix_payment_sessions_token", "payment_sessions", ["token"])
    op.create_index("ix_payment_sessions_merchant_reference", "payment_sessions", ["merchant_reference"])

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("payment_session_id", sa.Integer(), nullable=True),
        sa.Column("transaction_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("remaining_balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_session_id"], ["payment_sessions.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["customer_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_payment_transactions_transaction_id"),
    )
    op.create_index("ix_payment_transactions_workflow_id", "payment_transactions", ["workflow_id"])
    op.create_index("ix_payment_transactions_transaction_id", "payment_transactions", ["transaction_id"])

    op.create_table(
        "terms_acceptances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payment_session_id", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("terms_version", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["payment_session_id"], ["payment_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_session_id"),
    )
    op.create_index("ix_terms_acceptances_payment_session_id", "terms_acceptances", ["payment_session_id"])


def downgrade() -> None:
    op.drop_table("terms_acceptances")
    op.drop_table("payment_transactions")
    op.drop_table("payment_sessions")
    op.drop_table("customer_workflows")
