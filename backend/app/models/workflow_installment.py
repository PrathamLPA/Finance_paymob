"""Persisted installment schedule for a customer workflow."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.customer_workflow import CustomerWorkflow


class WorkflowInstallment(Base):
    __tablename__ = "workflow_installments"
    __table_args__ = (
        UniqueConstraint("workflow_id", "installment_number", name="uq_workflow_installment_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    installment_number: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date)
    notice_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )

    workflow: Mapped[CustomerWorkflow] = relationship(back_populates="installments")
