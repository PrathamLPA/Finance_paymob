"""Payment session model — secure token-based payment flow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text
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
    # installment_1 | full | customer_choice — how charge_amount was chosen
    charge_source: Mapped[str] = mapped_column(String(40), default="full")
    # When true the customer cannot change the amount on the payment page
    amount_locked: Mapped[bool] = mapped_column(default=True)
    # Set when this session charges a specific installment from the persisted plan
    installment_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    paymob_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    paymob_checkout_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merchant_reference: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), default=SESSION_PENDING)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bitrix fires lead updates constantly; comment once per link, not per event.
    link_commented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[CustomerWorkflow] = relationship(back_populates="payment_sessions")
    terms_acceptance: Mapped[Optional[TermsAcceptance]] = relationship(
        back_populates="payment_session", uselist=False, cascade="all, delete-orphan"
    )
