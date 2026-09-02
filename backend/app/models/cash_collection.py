"""Cash collection queue items (one per unpaid cash installment)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.customer_workflow import CustomerWorkflow
    from app.models.staff_user import StaffUser

STATUS_OPEN = "open"
STATUS_CLAIMED = "claimed"
STATUS_COLLECTED = "collected"
STATUS_CANCELLED = "cancelled"


class CashCollection(Base):
    __tablename__ = "cash_collections"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "installment_number",
            name="uq_cash_collection_workflow_installment",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    bitrix_lead_id: Mapped[int] = mapped_column(Integer, index=True)
    installment_number: Mapped[int] = mapped_column(Integer)
    course_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    due_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    collected_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN, index=True)
    claimed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("staff_users.id"), nullable=True, index=True
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("staff_users.id"), nullable=True, index=True
    )
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Customer fill-details + terms session (required before employee can collect)
    payment_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payment_sessions.id"), nullable=True, index=True
    )
    details_ready_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Photo / screenshot of cash handover (required at collect time)
    proof_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proof_content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    proof_original_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP)"),
        onupdate=datetime.utcnow,
    )

    workflow: Mapped[CustomerWorkflow] = relationship()
    claimed_by: Mapped[Optional[StaffUser]] = relationship(
        back_populates="claimed_collections",
        foreign_keys=[claimed_by_id],
    )
    collected_by: Mapped[Optional[StaffUser]] = relationship(
        back_populates="collected_collections",
        foreign_keys=[collected_by_id],
    )
