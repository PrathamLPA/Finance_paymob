"""Add participants JSON to terms acceptances."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "terms_acceptances",
        sa.Column("participants_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("terms_acceptances", "participants_json")
