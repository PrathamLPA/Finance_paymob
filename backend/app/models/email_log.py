"""Record of every email the system sends, so the admin can see what went out."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.data_mode import current_data_mode
from app.db.session import Base


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_mode: Mapped[str] = mapped_column(
        String(10), default=current_data_mode, server_default="test", index=True
    )
    to_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # sent | failed | mock (mock = SendGrid is not configured, written to a file only)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    provider_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    has_attachment: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"), index=True
    )
