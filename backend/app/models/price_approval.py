"""Manager approval for below-catalog selling prices."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.customer_workflow import CustomerWorkflow

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class PriceApproval(Base):
    __tablename__ = "price_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("customer_workflows.id"), index=True)
    bitrix_lead_id: Mapped[int] = mapped_column(Integer, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="AED")
    total_payable: Mapped[str] = mapped_column(String(32), default="0.00")
    catalog_minimum_total: Mapped[str] = mapped_column(String(32), default="0.00")
    reason: Mapped[str] = mapped_column(Text, default="")
    lines_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    lead_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    owner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    manager_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manager_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    manager_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )

    workflow: Mapped[CustomerWorkflow] = relationship(back_populates="price_approvals")
