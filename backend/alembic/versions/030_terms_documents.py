"""Editable, versioned Terms and Conditions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "terms_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("published_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("published_by_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index("ix_terms_documents_version", "terms_documents", ["version"])
    op.create_index("ix_terms_documents_is_active", "terms_documents", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_terms_documents_is_active", table_name="terms_documents")
    op.drop_index("ix_terms_documents_version", table_name="terms_documents")
    op.drop_table("terms_documents")
