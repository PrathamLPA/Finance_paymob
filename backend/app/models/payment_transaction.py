"""Payment transaction history with Paymob webhook fields."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.customer_workflow import CustomerWorkflow


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (UniqueConstraint("transaction_id", name="uq_payment_transactions_transaction_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    payment_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payment_sessions.id"), nullable=True, index=True
    )
    transaction_id: Mapped[str] = mapped_column(String(100), index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    remaining_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(50), default="success")
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"))

    # Paymob transaction callback fields
    amount_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paymob_created_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_occured: Mapped[bool] = mapped_column(Boolean, default=False)
    has_parent_transaction: Mapped[bool] = mapped_column(Boolean, default=False)
    paymob_integration_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_3d_secure: Mapped[bool] = mapped_column(Boolean, default=False)
    is_auth: Mapped[bool] = mapped_column(Boolean, default=False)
    is_capture: Mapped[bool] = mapped_column(Boolean, default=False)
    is_refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    is_standalone_payment: Mapped[bool] = mapped_column(Boolean, default=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, default=False)
    paymob_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    merchant_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    owner: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    source_pan: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_sub_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)

    workflow: Mapped[CustomerWorkflow] = relationship(back_populates="transactions")
