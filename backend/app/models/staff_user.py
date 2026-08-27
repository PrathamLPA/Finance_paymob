"""Staff users for Cash Desk (managers and cash-collection employees)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.cash_collection import CashCollection
    from app.models.cash_deposit import CashDeposit

ROLE_MANAGER = "manager"
ROLE_EMPLOYEE = "employee"


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=ROLE_EMPLOYEE, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP)"),
        onupdate=datetime.utcnow,
    )

    claimed_collections: Mapped[list[CashCollection]] = relationship(
        back_populates="claimed_by",
        foreign_keys="CashCollection.claimed_by_id",
    )
    collected_collections: Mapped[list[CashCollection]] = relationship(
        back_populates="collected_by",
        foreign_keys="CashCollection.collected_by_id",
    )
    deposits: Mapped[list[CashDeposit]] = relationship(
        back_populates="employee",
        foreign_keys="CashDeposit.employee_id",
    )
