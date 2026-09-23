"""Persistent round-robin cursors (e.g. B2C Ops department assignment)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

B2C_OPS_CURSOR_KEY = "b2c_ops_department"


class AssignmentCursor(Base):
    __tablename__ = "assignment_cursors"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP)"),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def claim_round_robin_ids(
    db,
    *,
    key: str,
    pool: list[int],
    count: int,
) -> list[int]:
    """Return ``count`` user ids from ``pool`` in order, advancing the cursor."""
    if not pool or count <= 0:
        return []
    row = db.get(AssignmentCursor, key)
    if row is None:
        row = AssignmentCursor(key=key, next_index=0)
        db.add(row)
        db.flush()
    start = int(row.next_index or 0) % len(pool)
    picked: list[int] = []
    for offset in range(count):
        picked.append(int(pool[(start + offset) % len(pool)]))
    row.next_index = (start + count) % len(pool)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return picked
