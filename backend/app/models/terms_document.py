"""Published versions of the Terms and Conditions that customers see and accept."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TermsDocument(Base):
    __tablename__ = "terms_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    published_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("staff_users.id"), nullable=True
    )
    published_by_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Exactly one row is active: the version shown to customers right now.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
