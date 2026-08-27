"""Cash deposits recorded by employees (reduces cash on hand)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.staff_user import StaffUser


class CashDeposit(Base):
    __tablename__ = "cash_deposits"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deposited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )

    employee: Mapped[StaffUser] = relationship(
        back_populates="deposits",
        foreign_keys=[employee_id],
    )
    recorded_by: Mapped[StaffUser] = relationship(foreign_keys=[recorded_by_id])
