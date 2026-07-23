"""Automated payment reminder processing."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import STATUS_PAID, STATUS_THRESHOLD_MET, CustomerWorkflow
from app.services.payment_session_service import PaymentSessionService

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.session_service = PaymentSessionService(db, self.settings)
        self.email = get_email_client(self.settings)
        self.bitrix = get_bitrix_client(self.settings)

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def workflows_due_for_reminder(self) -> list[CustomerWorkflow]:
        if not self.settings.reminder_enabled:
            return []

        interval = timedelta(hours=self.settings.reminder_interval_hours)
        now = self._utcnow()
        workflows = self.db.scalars(
            select(CustomerWorkflow).where(
                CustomerWorkflow.reminders_enabled.is_(True),
                CustomerWorkflow.payment_status.notin_([STATUS_THRESHOLD_MET, STATUS_PAID]),
            )
        ).all()

        due: list[CustomerWorkflow] = []
        for workflow in workflows:
            if workflow.total_amount <= 0 or workflow.remaining_balance <= 0:
                continue
            if workflow.meets_required_percent(self.settings.payment_required_percent):
                continue
            if not workflow.payment_sessions:
                continue
            reference = workflow.last_reminder_at or workflow.created_at
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            if now - reference >= interval:
                due.append(workflow)
        return due

    async def send_reminder(self, workflow: CustomerWorkflow) -> PaymentSession | None:
        session = await self.session_service.get_or_create_reusable_session(workflow)
        payment_url = self.session_service.build_payment_url(session.token)

        if workflow.customer_email:
            self.email.send_payment_request(
                to_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
            )

        if workflow.finance_deal_id:
            try:
                await self.bitrix.set_deal_payment_link(workflow.finance_deal_id, payment_url)
            except Exception:
                logger.exception("Failed to refresh Bitrix payment link for deal %s", workflow.finance_deal_id)

        workflow.last_reminder_at = self._utcnow()
        workflow.reminder_count = (workflow.reminder_count or 0) + 1
        self.db.commit()
        self.db.refresh(workflow)
        logger.info(
            "Reminder #%s sent for workflow %s (token %s...)",
            workflow.reminder_count,
            workflow.id,
            session.token[:8],
        )
        return session

    async def process_due_reminders(self) -> dict:
        due = self.workflows_due_for_reminder()
        sent = 0
        errors: list[str] = []
        for workflow in due:
            try:
                await self.send_reminder(workflow)
                sent += 1
            except Exception as exc:
                logger.exception("Reminder failed for workflow %s", workflow.id)
                errors.append(f"workflow {workflow.id}: {exc}")
        return {"due": len(due), "sent": sent, "errors": errors}
