"""Payment session model — secure token-based payment flow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.customer_workflow import CustomerWorkflow
    from app.models.terms_acceptance import TermsAcceptance

SESSION_PENDING = "pending"
SESSION_TERMS_ACCEPTED = "terms_accepted"
SESSION_COMPLETED = "completed"
SESSION_EXPIRED = "expired"

SOURCE_LEAD = "lead"
SOURCE_FINANCE_DEAL = "finance_deal"


class PaymentSession(Base):
    __tablename__ = "payment_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[int] = mapped_column()
    charge_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    paymob_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    paymob_checkout_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merchant_reference: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), default=SESSION_PENDING)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[CustomerWorkflow] = relationship(back_populates="payment_sessions")
    terms_acceptance: Mapped[Optional[TermsAcceptance]] = relationship(
        back_populates="payment_session", uselist=False, cascade="all, delete-orphan"
    )
