"""Automated payment reminder processing."""

from __future__ import annotations

import asyncio
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
    unpaid_installment_by_number,
)
from app.services.payment_session_service import PaymentSessionService
from app.services.email_validation import is_valid_email

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

    def _merge_deal_installment_fields(self, lead: dict, deal: dict) -> dict:
        """Fill blank lead installment UFs from the Finance deal (tunnel copy)."""
        if not deal:
            return lead
        merged = dict(lead or {})
        codes = [
            self.settings.bitrix_field_installment_count,
            self.settings.bitrix_field_installment_1,
            self.settings.bitrix_field_installment_1_date,
            self.settings.bitrix_field_installment_2,
            self.settings.bitrix_field_installment_2_due_date,
            self.settings.bitrix_field_installment_3,
            self.settings.bitrix_field_installment_3_due_date,
            self.settings.bitrix_field_installment_4,
            self.settings.bitrix_field_installment_4_due_date,
            self.settings.bitrix_field_payment_1_mode,
            self.settings.bitrix_field_payment_2_mode,
            self.settings.bitrix_field_payment_3_mode,
            self.settings.bitrix_field_payment_4_mode,
        ]
        for code in codes:
            if not code:
                continue
            current = merged.get(code)
            if current not in (None, "", [], {}, 0, "0"):
                continue
            value = deal.get(code)
            if value not in (None, "", [], {}, 0, "0"):
                merged[code] = value
        return merged

    async def _client_email(self, workflow: CustomerWorkflow, lead: dict) -> str | None:
        email, _ = await self.bitrix.resolve_customer_details(lead)
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

    async def send_reminder(
        self,
        workflow: CustomerWorkflow,
        *,
        early_days: int = 0,
        force_installment_number: int | None = None,
        lead_override: dict | None = None,
    ) -> PaymentSession | None:
        from app.services.installment_charge import ChargePlan
        from app.services.installment_plan import resolve_first_charge_for_workflow
        from app.services.workflow_orchestrator import WorkflowOrchestrator

        refreshing_expired = self._needs_expired_link_refresh(workflow)

        lead = dict(lead_override) if isinstance(lead_override, dict) else self._lead_payload(workflow)
        orchestrator = WorkflowOrchestrator(self.db, self.settings)
        if lead_override is None:
            try:
                fresh = await self.bitrix.get_lead(workflow.bitrix_lead_id)
                if fresh:
                    lead = fresh
                    await orchestrator.sync_workflow_from_lead(workflow, lead=fresh)
            except Exception:
                logger.exception(
                    "Could not refresh Bitrix lead %s for reminder", workflow.bitrix_lead_id
                )

        # Always charge Installment 1 (or remaining) — never silently fall back to full total
        # just because charge_amount was omitted.
        plan = resolve_first_charge_for_workflow(
            workflow, lead=lead, settings=self.settings
        )
        from app.services.installment_plan import charge_installment_number_for_workflow

        installment_number = charge_installment_number_for_workflow(workflow)
        if installment_number is None and plan.source == "installment_1":
            installment_number = 1
        if force_installment_number is not None:
            installment_number = force_installment_number
            forced = unpaid_installment_by_number(
                lead,
                self.settings,
                amount_paid=workflow.amount_paid,
                installment_number=force_installment_number,
            )
            if forced and forced.amount and forced.amount > 0:
                remaining = workflow.remaining_balance
                charge = forced.amount
                if remaining > 0 and charge > remaining:
                    charge = remaining
                plan = ChargePlan(
                    amount=charge,
                    source=f"installment_{force_installment_number}",
                    label=f"Installment {force_installment_number}",
                    locked=True,
                )

        from app.services.payment_mode import (
            resolve_is_bank_transfer_payment_mode,
            resolve_is_cash_payment_mode,
        )
        from app.models.payment_session import CHANNEL_BANK_TRANSFER, CHANNEL_ONLINE
        from app.services.bank_transfer_service import BankTransferService

        number_for_mode = installment_number or 1
        # Later installments: blank mode → online Paymob link.
        # Only honor cash/bank if that installment's own Payment Mode UF is set.
        mode_fallback = force_installment_number is None
        if await resolve_is_cash_payment_mode(
            lead,
            installment_number=number_for_mode,
            settings=self.settings,
            bitrix=self.bitrix,
            allow_cross_installment_fallback=mode_fallback,
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
            allow_cross_installment_fallback=mode_fallback,
        ):
            channel = CHANNEL_BANK_TRANSFER

        if channel == CHANNEL_ONLINE:
            billing_email = (workflow.customer_email or "").strip()
            if billing_email and not is_valid_email(billing_email):
                await orchestrator._comment_invalid_customer_email(
                    workflow, billing_email
                )
                workflow.last_reminder_at = self._utcnow()
                self.db.commit()
                return None
            if orchestrator.is_known_invalid_paymob_email(workflow):
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
        from app.services.payment_mode import is_payment_mode_blank

        if is_payment_mode_blank(
            lead, installment_number=number_for_mode, settings=self.settings
        ):
            await orchestrator._comment_missing_payment_mode(
                installment_number=number_for_mode,
                entity_type="LEAD" if workflow.bitrix_lead_id else "DEAL",
                entity_id=workflow.bitrix_lead_id or workflow.finance_deal_id or 0,
                payment_url=payment_url,
            )
        logger.info(
            "Reminder charge plan | workflow_id=%s source=%s amount=%s %s token=%s...",
            workflow.id,
            plan.source,
            f"{plan.amount:.2f}",
            workflow.currency,
            session.token[:8],
        )

        client_email = await self._client_email(workflow, lead)
        if client_email and not is_valid_email(client_email):
            await orchestrator._comment_invalid_customer_email(workflow, client_email)
            client_email = None
        elif client_email:
            workflow.customer_email = client_email

        slot = None
        if force_installment_number is not None:
            slot = unpaid_installment_by_number(
                lead,
                self.settings,
                amount_paid=workflow.amount_paid,
                installment_number=force_installment_number,
            )
            if slot and str(slot.number) in self._notices_sent(workflow):
                slot = None
        elif self.settings.installment_due_notices_enabled and is_installment_plan(lead, self.settings):
            slot = next_due_installment(
                lead,
                self.settings,
                amount_paid=workflow.amount_paid,
                today=today_in_dubai(),
                early_days=early_days,
            )
            if slot and str(slot.number) in self._notices_sent(workflow):
                slot = None

        if client_email and slot:
            amount = f"{slot.amount:.2f}" if slot.amount is not None else None
            await asyncio.to_thread(
                self.email.send_installment_reminder,
                to_email=client_email,
                customer_name=workflow.customer_name,
                payment_url=payment_url,
                installment_number=slot.number,
                due_date=slot.due_date.isoformat(),
                amount=amount,
                currency=workflow.currency,
            )
        elif client_email:
            await asyncio.to_thread(
                self.email.send_payment_request,
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

    async def process_bitrix_installment_due(
        self,
        finance_deal_id: int,
        *,
        installment_number: int | None = None,
    ) -> dict:
        """Issue Paymob link + client email when Bitrix BP fires for an installment due date.

        Independent of ``installment_due_notices_enabled`` (that flag only gates the poller).
        Idempotent per installment number via ``installment_notices_sent``.
        """
        from app.services.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(self.db, self.settings)
        try:
            workflow, deal = await orchestrator.resolve_workflow_for_bitrix_deal(
                finance_deal_id
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        # Threshold % (e.g. 50%) can already be met while Installment 2+ is still unpaid.
        if (workflow.total_amount or 0) <= 0 or workflow.remaining_balance <= 0:
            return {
                "status": "ignored",
                "reason": "already_paid",
                "workflow_id": workflow.id,
            }

        lead = self._lead_payload(workflow)
        try:
            fresh = await self.bitrix.get_lead(workflow.bitrix_lead_id)
            if fresh:
                lead = fresh
                await orchestrator.sync_workflow_from_lead(workflow, lead=fresh)
        except Exception:
            logger.exception(
                "Could not refresh Bitrix lead %s for installment-due deal %s",
                workflow.bitrix_lead_id,
                finance_deal_id,
            )

        # Finance tunnel often holds installment UFs while the converted lead does not.
        lead = self._merge_deal_installment_fields(lead, deal if isinstance(deal, dict) else {})

        if not is_installment_plan(lead, self.settings):
            return {
                "status": "ignored",
                "reason": "not_installment_plan",
                "workflow_id": workflow.id,
            }

        # Bitrix Pause wakes 1 day before due — allow early_days=1.
        if installment_number is not None:
            slot = unpaid_installment_by_number(
                lead,
                self.settings,
                amount_paid=workflow.amount_paid,
                installment_number=installment_number,
            )
            if slot is None:
                return {
                    "status": "ignored",
                    "reason": "installment_already_paid_or_missing",
                    "workflow_id": workflow.id,
                    "installment_number": installment_number,
                }
        else:
            slot = next_due_installment(
                lead,
                self.settings,
                amount_paid=workflow.amount_paid,
                today=today_in_dubai(),
                early_days=1,
            )

        if slot is None:
            return {
                "status": "ignored",
                "reason": "no_unpaid_installment_due",
                "workflow_id": workflow.id,
            }

        if str(slot.number) in self._notices_sent(workflow):
            return {
                "status": "ignored",
                "reason": "notice_already_sent",
                "workflow_id": workflow.id,
                "installment_number": slot.number,
            }

        # Reuse send_reminder charge/email path (poller flag does not gate this webhook).
        session = await self.send_reminder(
            workflow,
            early_days=1,
            force_installment_number=slot.number,
            lead_override=lead,
        )

        payment_url = None
        if session is not None:
            payment_url = self.session_service.build_payment_url(session.token)
        elif workflow.finance_deal_id:
            try:
                deal = await self.bitrix.get_deal(workflow.finance_deal_id)
                payment_url = (deal or {}).get(self.settings.bitrix_field_payment_link)
            except Exception:
                payment_url = None

        # send_reminder marks notices_sent when it emailed the installment slot.
        self.db.refresh(workflow)
        if str(slot.number) not in self._notices_sent(workflow) and payment_url:
            sent = self._notices_sent(workflow)
            sent[str(slot.number)] = slot.due_date.isoformat()
            workflow.installment_notices_sent = sent
            flag_modified(workflow, "installment_notices_sent")
            self.db.commit()

        return {
            "status": "processed",
            "source": "bitrix_installment_due",
            "workflow_id": workflow.id,
            "installment_number": slot.number,
            "due_date": slot.due_date.isoformat(),
            "payment_url": payment_url,
        }

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
