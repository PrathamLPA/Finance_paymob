"""Small key/value flags the admin screen can change without a redeploy."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

KEY_FINANCE_MANAGER_VERIFICATION = "finance_manager_verification"


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("staff_users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )
