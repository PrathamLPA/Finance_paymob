"""Delete every payment record of one data mode (test or live), children first."""

from __future__ import annotations

import logging

from sqlalchemy import Table, delete, select
from sqlalchemy.orm import Session

from app.db.session import Base

logger = logging.getLogger(__name__)

# Tables that carry a data_mode stamp. Everything that hangs off them (installments,
# terms acceptances, price approvals, ...) is removed through its foreign keys.
ROOT_TABLES = (
    "customer_workflows",
    "payment_sessions",
    "payment_transactions",
    "cash_collections",
    "cash_deposits",
    "bank_transfer_submissions",
    "finance_verifications",
    "email_logs",
)


def _children_of(table: Table) -> list[tuple[Table, str, str]]:
    """Tables with a foreign key into `table`: (child table, child column, parent column)."""
    found: list[tuple[Table, str, str]] = []
    for other in Base.metadata.tables.values():
        for fk in other.foreign_keys:
            if fk.column.table is table:
                found.append((other, fk.parent.name, fk.column.name))
    return found


def _delete_where(db: Session, table: Table, condition, counts: dict[str, int], seen: set[str]) -> None:
    """Delete rows of `table` matching `condition`, after the rows that point at them."""
    if table.name in seen:
        # A table reached twice (or a cycle): its rows are handled on the first visit.
        return
    seen = seen | {table.name}
    for child, child_col, parent_col in _children_of(table):
        if child.name in seen:
            continue
        parent_keys = select(table.c[parent_col]).where(condition)
        _delete_where(db, child, child.c[child_col].in_(parent_keys), counts, seen)
    result = db.execute(delete(table).where(condition))
    counts[table.name] = counts.get(table.name, 0) + int(result.rowcount or 0)


def clear_mode_data(db: Session, mode: str) -> dict[str, int]:
    """Remove all payment data stamped with `mode`. Returns rows deleted per table."""
    counts: dict[str, int] = {}
    tables = Base.metadata.tables
    # Children are removed inside _delete_where, so order only matters between roots:
    # workflows own the most, so clear them last.
    order = [name for name in ROOT_TABLES if name != "customer_workflows"] + ["customer_workflows"]
    for name in order:
        table = tables[name]
        _delete_where(db, table, table.c.data_mode == mode, counts, set())
    db.commit()
    logger.warning("Cleared %s payment data | %s", mode, counts)
    return {name: n for name, n in counts.items() if n}
