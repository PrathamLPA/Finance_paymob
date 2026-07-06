"""Terms and conditions acceptance record."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.payment_session import PaymentSession


class TermsAcceptance(Base):
    __tablename__ = "terms_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_session_id: Mapped[int] = mapped_column(ForeignKey("payment_sessions.id"), unique=True, index=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    terms_version: Mapped[str] = mapped_column(String(20))

    payment_session: Mapped[PaymentSession] = relationship(back_populates="terms_acceptance")
