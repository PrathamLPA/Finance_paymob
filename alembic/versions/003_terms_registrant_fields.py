"""Add registrant fields to terms acceptances."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("terms_acceptances", sa.Column("course_for", sa.String(length=20), nullable=True))
    op.add_column("terms_acceptances", sa.Column("registrant_name", sa.String(length=255), nullable=True))
    op.add_column("terms_acceptances", sa.Column("registrant_email", sa.String(length=320), nullable=True))
    op.add_column("terms_acceptances", sa.Column("registrant_phone", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("terms_acceptances", "registrant_phone")
    op.drop_column("terms_acceptances", "registrant_email")
    op.drop_column("terms_acceptances", "registrant_name")
    op.drop_column("terms_acceptances", "course_for")
