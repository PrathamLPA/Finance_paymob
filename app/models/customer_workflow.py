"""Customer workflow model — central entity per customer journey."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.payment_session import PaymentSession
    from app.models.payment_transaction import PaymentTransaction


class CustomerWorkflow(Base):
    __tablename__ = "customer_workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    bitrix_lead_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    sales_deal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    finance_deal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    b2c_deal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    zoho_invoice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_payment_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP)"),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    payment_sessions: Mapped[list[PaymentSession]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[PaymentTransaction]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )

    @property
    def remaining_balance(self) -> Decimal:
        return max(self.total_amount - self.amount_paid, Decimal("0.00"))

    @property
    def is_first_payment_pending(self) -> bool:
        return self.first_payment_at is None
