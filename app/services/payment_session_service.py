"""Payment session lifecycle management."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import get_paymob_client
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import (
    SESSION_COMPLETED,
    SESSION_EXPIRED,
    SESSION_PENDING,
    SESSION_TERMS_ACCEPTED,
    SOURCE_FINANCE_DEAL,
    SOURCE_LEAD,
    PaymentSession,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PaymentSessionService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.paymob = get_paymob_client(self.settings)

    def get_session_by_token(self, token: str) -> PaymentSession | None:
        return self.db.scalar(select(PaymentSession).where(PaymentSession.token == token))

    def get_active_session_by_token(self, token: str) -> PaymentSession | None:
        session = self.get_session_by_token(token)
        if not session:
            return None
        if session.status in (SESSION_COMPLETED, SESSION_EXPIRED):
            return None
        if _ensure_utc(session.expires_at) <= _utcnow():
            session.status = SESSION_EXPIRED
            self.db.commit()
            return None
        return session

    async def create_session(
        self,
        workflow: CustomerWorkflow,
        *,
        source_type: str,
        source_id: int,
    ) -> PaymentSession:
        charge_amount = workflow.remaining_balance if workflow.amount_paid > 0 else workflow.total_amount
        if charge_amount <= 0 and workflow.total_amount > 0:
            charge_amount = workflow.total_amount

        merchant_reference = f"WF-{workflow.id}-{uuid.uuid4().hex[:8]}"
        paymob_session = await self.paymob.create_payment_session(
            amount=charge_amount,
            currency=workflow.currency,
            merchant_reference=merchant_reference,
            customer_email=workflow.customer_email,
            customer_name=workflow.customer_name,
        )

        token = secrets.token_urlsafe(32)
        session = PaymentSession(
            workflow_id=workflow.id,
            token=token,
            source_type=source_type,
            source_id=source_id,
            charge_amount=charge_amount,
            currency=workflow.currency,
            paymob_session_id=paymob_session.session_id,
            paymob_checkout_url=paymob_session.checkout_url,
            merchant_reference=merchant_reference,
            status=SESSION_PENDING,
            expires_at=_utcnow() + timedelta(hours=self.settings.payment_session_ttl_hours),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def mark_terms_accepted(self, session: PaymentSession) -> None:
        session.status = SESSION_TERMS_ACCEPTED
        self.db.commit()

    def mark_completed(self, session: PaymentSession) -> None:
        session.status = SESSION_COMPLETED
        session.completed_at = _utcnow()
        self.db.commit()

    def build_payment_url(self, token: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/payment/{token}"

    @staticmethod
    def source_lead(lead_id: int) -> tuple[str, int]:
        return SOURCE_LEAD, lead_id

    @staticmethod
    def source_finance_deal(deal_id: int) -> tuple[str, int]:
        return SOURCE_FINANCE_DEAL, deal_id
