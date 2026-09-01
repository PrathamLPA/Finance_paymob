"""Bank transfer receipt submissions awaiting finance approval."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.customer_workflow import CustomerWorkflow
    from app.models.payment_session import PaymentSession
    from app.models.staff_user import StaffUser

STATUS_AWAITING_UPLOAD = "awaiting_upload"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

CHANNEL_BANK_TRANSFER = "bank_transfer"


class BankTransferSubmission(Base):
    __tablename__ = "bank_transfer_submissions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "installment_number",
            name="uq_bank_transfer_workflow_installment",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    payment_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payment_sessions.id"), nullable=True, index=True
    )
    bitrix_lead_id: Mapped[int] = mapped_column(Integer, index=True)
    bitrix_estimate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    installment_number: Mapped[int] = mapped_column(Integer)
    course_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    due_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    status: Mapped[str] = mapped_column(String(30), default=STATUS_AWAITING_UPLOAD, index=True)
    proof_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proof_content_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    proof_original_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("staff_users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bitrix_lead_comment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bitrix_estimate_comment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP)"),
        onupdate=datetime.utcnow,
    )

    workflow: Mapped[CustomerWorkflow] = relationship()
    payment_session: Mapped[Optional[PaymentSession]] = relationship()
    reviewed_by: Mapped[Optional[StaffUser]] = relationship(foreign_keys=[reviewed_by_id])
