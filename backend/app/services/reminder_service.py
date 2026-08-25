"""Automated payment reminder processing."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import get_bitrix_client, get_email_client
from app.models.customer_workflow import STATUS_PAID, STATUS_THRESHOLD_MET, CustomerWorkflow
from app.models.payment_session import PaymentSession
from app.services.installment_notices import (
    is_installment_plan,
    next_due_installment,
    today_in_dubai,
)
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

    def _lead_payload(self, workflow: CustomerWorkflow) -> dict:
        return workflow.bitrix_lead_payload if isinstance(workflow.bitrix_lead_payload, dict) else {}

    def _client_email(self, workflow: CustomerWorkflow, lead: dict) -> str | None:
        email, _ = self.bitrix.extract_customer_details(lead)
        return email or workflow.customer_email

    def _notices_sent(self, workflow: CustomerWorkflow) -> dict:
        raw = workflow.installment_notices_sent
        return dict(raw) if isinstance(raw, dict) else {}

    def _installment_notice_pending(self, workflow: CustomerWorkflow, lead: dict) -> bool:
        if not self.settings.installment_due_notices_enabled:
            return False
        if not is_installment_plan(lead, self.settings):
            return False
        slot = next_due_installment(
            lead,
            self.settings,
            amount_paid=workflow.amount_paid,
            today=today_in_dubai(),
        )
        if slot is None:
            return False
        return str(slot.number) not in self._notices_sent(workflow)

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
            lead = self._lead_payload(workflow)
            if self._installment_notice_pending(workflow, lead):
                due.append(workflow)
                continue
            if is_installment_plan(lead, self.settings):
                # Date-based notices only; skip the 24h interval for installment plans.
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

        lead = self._lead_payload(workflow)
        try:
            fresh = await self.bitrix.get_lead(workflow.bitrix_lead_id)
            if fresh:
                lead = fresh
                workflow.bitrix_lead_payload = fresh
        except Exception:
            logger.exception("Could not refresh Bitrix lead %s for reminder", workflow.bitrix_lead_id)

        client_email = self._client_email(workflow, lead)
        if client_email:
            workflow.customer_email = client_email

        slot = None
        if self.settings.installment_due_notices_enabled and is_installment_plan(lead, self.settings):
            slot = next_due_installment(
                lead,
                self.settings,
                amount_paid=workflow.amount_paid,
                today=today_in_dubai(),
            )
            if slot and str(slot.number) in self._notices_sent(workflow):
                slot = None

        if client_email and slot:
            amount = f"{slot.amount:.2f}" if slot.amount is not None else None
            self.email.send_installment_reminder(
                to_email=client_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
                installment_number=slot.number,
                due_date=slot.due_date.isoformat(),
                amount=amount,
                currency=workflow.currency,
            )
        elif client_email:
            self.email.send_payment_request(
                to_email=client_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
            )

        comment = f"Payment reminder link: {payment_url}"
        if slot:
            comment = (
                f"Installment {slot.number} due {slot.due_date.isoformat()} — "
                f"client emailed at {client_email or 'no-email'}\n{payment_url}"
            )
        if workflow.finance_deal_id:
            try:
                await self.bitrix.set_deal_payment_link(workflow.finance_deal_id, payment_url)
                await self.bitrix.add_timeline_comment(
                    entity_type="DEAL",
                    entity_id=workflow.finance_deal_id,
                    comment=comment,
                )
            except Exception:
                logger.exception("Failed to refresh Bitrix payment link for deal %s", workflow.finance_deal_id)
        elif workflow.bitrix_lead_id:
            try:
                await self.bitrix.add_timeline_comment(
                    entity_type="LEAD",
                    entity_id=workflow.bitrix_lead_id,
                    comment=comment,
                )
            except Exception:
                logger.exception(
                    "Failed to post reminder comment on Bitrix lead %s", workflow.bitrix_lead_id
                )

        if slot:
            sent = self._notices_sent(workflow)
            sent[str(slot.number)] = slot.due_date.isoformat()
            workflow.installment_notices_sent = sent
            flag_modified(workflow, "installment_notices_sent")

        workflow.last_reminder_at = self._utcnow()
        workflow.reminder_count = (workflow.reminder_count or 0) + 1
        self.db.commit()
        self.db.refresh(workflow)
        logger.info(
            "Reminder #%s sent for workflow %s (token %s... installment=%s)",
            workflow.reminder_count,
            workflow.id,
            session.token[:8],
            slot.number if slot else "-",
        )
        return session

    async def process_due_reminders(self) -> dict:
        open_workflows = self.db.scalars(
            select(CustomerWorkflow).where(
                CustomerWorkflow.reminders_enabled.is_(True),
                CustomerWorkflow.payment_status.notin_([STATUS_THRESHOLD_MET, STATUS_PAID]),
            )
        ).all()
        for workflow in open_workflows:
            try:
                lead = await self.bitrix.get_lead(workflow.bitrix_lead_id)
                if lead:
                    workflow.bitrix_lead_payload = lead
            except Exception:
                logger.exception("Could not refresh Bitrix lead %s before reminder scan", workflow.bitrix_lead_id)
        self.db.commit()

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
