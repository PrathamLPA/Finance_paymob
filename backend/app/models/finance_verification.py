"""Hold a recorded payment until a finance manager releases the rest of the flow."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class FinanceVerification(Base):
    __tablename__ = "finance_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("payment_transactions.id"), unique=True, index=True
    )
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    bitrix_lead_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    amount: Mapped[str] = mapped_column(String(32), default="0.00")
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    comment_prefix: Mapped[str] = mapped_column(Text, default="Payment successful")
    skip_zoho: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_deals: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("staff_users.id"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
