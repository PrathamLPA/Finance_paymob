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

    def _has_open_balance(self, workflow: CustomerWorkflow) -> bool:
        if workflow.total_amount <= 0 or workflow.remaining_balance <= 0:
            return False
        if workflow.meets_required_percent(self.settings.payment_required_percent):
            return False
        return True

    def _needs_expired_link_refresh(self, workflow: CustomerWorkflow) -> bool:
        """True when payment is still owed but every payment link has expired."""
        if not self._has_open_balance(workflow):
            return False
        if self.session_service.get_active_session_for_workflow(workflow):
            return False
        sessions = list(workflow.payment_sessions or [])
        if not sessions:
            return False
        # At least one link was issued before; none are usable now.
        return True

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
        seen: set[int] = set()
        for workflow in workflows:
            if not self._has_open_balance(workflow):
                continue

            # Expired unpaid link → issue and share a new one immediately.
            if self._needs_expired_link_refresh(workflow):
                due.append(workflow)
                seen.add(workflow.id)
                continue

            if not workflow.payment_sessions:
                continue
            lead = self._lead_payload(workflow)
            if self._installment_notice_pending(workflow, lead):
                due.append(workflow)
                seen.add(workflow.id)
                continue
            if is_installment_plan(lead, self.settings):
                # Date-based notices only; skip the 24h interval for installment plans.
                continue
            reference = workflow.last_reminder_at or workflow.created_at
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            if now - reference >= interval and workflow.id not in seen:
                due.append(workflow)
                seen.add(workflow.id)
        return due

    async def send_reminder(self, workflow: CustomerWorkflow) -> PaymentSession | None:
        from app.services.installment_plan import resolve_first_charge_for_workflow
        from app.services.workflow_orchestrator import WorkflowOrchestrator

        refreshing_expired = self._needs_expired_link_refresh(workflow)

        lead = self._lead_payload(workflow)
        orchestrator = WorkflowOrchestrator(self.db, self.settings)
        try:
            fresh = await self.bitrix.get_lead(workflow.bitrix_lead_id)
            if fresh:
                lead = fresh
                await orchestrator.sync_workflow_from_lead(workflow, lead=fresh)
        except Exception:
            logger.exception("Could not refresh Bitrix lead %s for reminder", workflow.bitrix_lead_id)

        # Always charge Installment 1 (or remaining) — never silently fall back to full total
        # just because charge_amount was omitted.
        plan = resolve_first_charge_for_workflow(
            workflow, lead=lead, settings=self.settings
        )
        from app.services.installment_plan import charge_installment_number_for_workflow

        installment_number = charge_installment_number_for_workflow(workflow)
        if installment_number is None and plan.source == "installment_1":
            installment_number = 1

        from app.services.payment_mode import (
            resolve_is_bank_transfer_payment_mode,
            resolve_is_cash_payment_mode,
        )
        from app.models.payment_session import CHANNEL_BANK_TRANSFER, CHANNEL_ONLINE
        from app.services.bank_transfer_service import BankTransferService

        number_for_mode = installment_number or 1
        if await resolve_is_cash_payment_mode(
            lead,
            installment_number=number_for_mode,
            settings=self.settings,
            bitrix=self.bitrix,
        ):
            try:
                await orchestrator.queue_cash_with_intake_link(
                    workflow,
                    lead=lead,
                    due_amount=plan.amount,
                    installment_number=number_for_mode,
                    entity_type="LEAD",
                    entity_id=workflow.bitrix_lead_id,
                    charge_source=plan.source,
                    amount_locked=plan.locked,
                )
            except Exception as exc:
                from app.services.cash_collection_service import CashCollectionQueued

                if isinstance(exc, CashCollectionQueued):
                    logger.info(
                        "Reminder cash intake queued | workflow_id=%s installment=%s",
                        workflow.id,
                        number_for_mode,
                    )
                    return None
                raise

        channel = CHANNEL_ONLINE
        if await resolve_is_bank_transfer_payment_mode(
            lead,
            installment_number=number_for_mode,
            settings=self.settings,
            bitrix=self.bitrix,
        ):
            channel = CHANNEL_BANK_TRANSFER

        if channel == CHANNEL_ONLINE and orchestrator.is_known_invalid_paymob_email(workflow):
            logger.info(
                "Reminder skipped quietly — known invalid Paymob email | "
                "workflow_id=%s lead_id=%s email=%s",
                workflow.id,
                workflow.bitrix_lead_id,
                (workflow.customer_email or "").strip() or "(missing)",
            )
            # Keep Bitrix timeline visible for agents (deduped inside notify).
            await orchestrator.notify_paymob_link_failure(
                workflow,
                reason=(
                    'Paymob intention failed (400): '
                    '{"billing_data":{"email":["Enter a valid email address."]}}'
                ),
                trigger="reminder (deferred)",
            )
            workflow.last_reminder_at = self._utcnow()
            self.db.commit()
            return None

        try:
            session = await self.session_service.get_or_create_reusable_session(
                workflow,
                charge_amount=plan.amount,
                charge_source=plan.source,
                amount_locked=plan.locked,
                installment_number=installment_number,
                channel=channel,
            )
        except ValueError as exc:
            reason = str(exc)
            if (
                channel == CHANNEL_ONLINE
                and "Paymob intention failed" in reason
                and WorkflowOrchestrator._is_invalid_email_paymob_reason(reason)
            ):
                # notify_paymob_link_failure already ran inside session create
                logger.warning(
                    "Reminder deferred — Paymob rejected billing email | "
                    "workflow_id=%s lead_id=%s email=%s",
                    workflow.id,
                    workflow.bitrix_lead_id,
                    (workflow.customer_email or "").strip() or "(missing)",
                )
                workflow.last_reminder_at = self._utcnow()
                self.db.commit()
                return None
            raise
        if channel == CHANNEL_BANK_TRANSFER:
            BankTransferService(self.db, self.settings).enqueue_for_session(
                session, lead=lead
            )
        replaced = bool(getattr(session, "_replaced_previous_link", False)) or refreshing_expired
        if replaced:
            session._replaced_previous_link = True  # type: ignore[attr-defined]

        payment_url = self.session_service.build_payment_url(session.token)
        logger.info(
            "Reminder charge plan | workflow_id=%s source=%s amount=%s %s token=%s...",
            workflow.id,
            plan.source,
            f"{plan.amount:.2f}",
            workflow.currency,
            session.token[:8],
        )

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

        orchestrator = WorkflowOrchestrator(self.db, self.settings)
        if workflow.finance_deal_id:
            try:
                await self.bitrix.set_deal_payment_link(workflow.finance_deal_id, payment_url)
            except Exception:
                logger.exception(
                    "Failed to refresh Bitrix payment link field for deal %s",
                    workflow.finance_deal_id,
                )
            await orchestrator.announce_payment_link(
                session,
                entity_type="DEAL",
                entity_id=workflow.finance_deal_id,
                force=True,
            )
        elif workflow.bitrix_lead_id:
            await orchestrator.announce_payment_link(
                session,
                entity_type="LEAD",
                entity_id=workflow.bitrix_lead_id,
                force=True,
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
            "Reminder #%s sent for workflow %s (token %s... installment=%s expired_refresh=%s)",
            workflow.reminder_count,
            workflow.id,
            session.token[:8],
            slot.number if slot else "-",
            refreshing_expired,
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
                    from app.services.workflow_orchestrator import WorkflowOrchestrator

                    await WorkflowOrchestrator(self.db, self.settings).sync_workflow_from_lead(
                        workflow, lead=lead
                    )
            except Exception as exc:
                message = str(exc).lower()
                if "not found" in message:
                    logger.warning(
                        "Disabling reminders — Bitrix lead %s not found (workflow %s)",
                        workflow.bitrix_lead_id,
                        workflow.id,
                    )
                    workflow.reminders_enabled = False
                else:
                    logger.exception(
                        "Could not refresh Bitrix lead %s before reminder scan",
                        workflow.bitrix_lead_id,
                    )
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
