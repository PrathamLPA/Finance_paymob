"""Add proof photo fields to cash collections."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cash_collections", sa.Column("proof_path", sa.Text(), nullable=True))
    op.add_column(
        "cash_collections",
        sa.Column("proof_content_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "cash_collections",
        sa.Column("proof_original_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cash_collections", "proof_original_name")
    op.drop_column("cash_collections", "proof_content_type")
    op.drop_column("cash_collections", "proof_path")
