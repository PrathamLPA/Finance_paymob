"""Add Paymob webhook columns and customer phone."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_paymob_fields"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer_workflows", sa.Column("customer_phone", sa.String(length=30), nullable=True))

    op.add_column("payment_transactions", sa.Column("amount_cents", sa.Integer(), nullable=True))
    op.add_column("payment_transactions", sa.Column("paymob_created_at", sa.String(length=50), nullable=True))
    op.add_column("payment_transactions", sa.Column("error_occured", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("has_parent_transaction", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("paymob_integration_id", sa.Integer(), nullable=True))
    op.add_column("payment_transactions", sa.Column("is_3d_secure", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("is_auth", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("is_capture", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("is_refunded", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("is_standalone_payment", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("payment_transactions", sa.Column("is_voided", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("paymob_order_id", sa.String(length=100), nullable=True))
    op.add_column("payment_transactions", sa.Column("merchant_order_id", sa.String(length=100), nullable=True))
    op.add_column("payment_transactions", sa.Column("owner", sa.Integer(), nullable=True))
    op.add_column("payment_transactions", sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("payment_transactions", sa.Column("source_pan", sa.String(length=50), nullable=True))
    op.add_column("payment_transactions", sa.Column("source_sub_type", sa.String(length=50), nullable=True))
    op.add_column("payment_transactions", sa.Column("source_type", sa.String(length=50), nullable=True))
    op.add_column("payment_transactions", sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column("customer_workflows", "customer_phone")
    for col in [
        "amount_cents", "paymob_created_at", "error_occured", "has_parent_transaction",
        "paymob_integration_id", "is_3d_secure", "is_auth", "is_capture", "is_refunded",
        "is_standalone_payment", "is_voided", "paymob_order_id", "merchant_order_id",
        "owner", "pending", "source_pan", "source_sub_type", "source_type", "success",
    ]:
        op.drop_column("payment_transactions", col)
