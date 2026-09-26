"""Payment session lifecycle management."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.factory import (
    get_bitrix_client,
    get_paymob_client,
    get_tabby_client,
    get_tamara_client,
)
from app.models.customer_workflow import CustomerWorkflow
from app.models.payment_session import (
    CHANNEL_BANK_TRANSFER,
    CHANNEL_CASH,
    CHANNEL_ONLINE,
    SESSION_COMPLETED,
    SESSION_EXPIRED,
    SESSION_PENDING,
    SESSION_TERMS_ACCEPTED,
    SOURCE_FINANCE_DEAL,
    SOURCE_LEAD,
    PaymentSession,
)

logger = logging.getLogger(__name__)


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
        self.tabby = get_tabby_client(self.settings)
        self.tamara = get_tamara_client(self.settings)

    async def _create_paymob_session(
        self,
        workflow: CustomerWorkflow,
        *,
        amount: Decimal,
        currency: str,
        merchant_reference: str,
        trigger: str,
        installment_number: int | None = None,
        payment_method_ids: list[int] | None = None,
    ):
        methods = payment_method_ids
        if methods is None:
            methods = await self._resolve_paymob_methods(
                workflow, installment_number=installment_number
            )
        try:
            return await self.paymob.create_payment_session(
                amount=amount,
                currency=currency,
                merchant_reference=merchant_reference,
                customer_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                payment_method_ids=methods,
            )
        except ValueError as exc:
            msg = str(exc)
            if "Paymob intention failed" in msg:
                from app.services.workflow_orchestrator import WorkflowOrchestrator

                orchestrator = WorkflowOrchestrator(self.db, self.settings)
                try:
                    await orchestrator.notify_paymob_link_failure(
                        workflow,
                        reason=msg,
                        trigger=trigger,
                    )
                except Exception:
                    logger.exception(
                        "Failed to notify Bitrix about Paymob error for lead %s",
                        workflow.bitrix_lead_id,
                    )
            raise

    async def _resolve_paymob_methods(
        self,
        workflow: CustomerWorkflow,
        *,
        installment_number: int | None,
        customer_payment_mode: str | None = None,
    ) -> list[int]:
        from app.integrations.factory import get_bitrix_client
        from app.services.payment_mode import resolve_paymob_payment_method_ids_async

        _ = customer_payment_mode  # unused: Bitrix Payment Mode is authoritative
        number = installment_number or 1
        bitrix = get_bitrix_client(self.settings)
        lead = workflow.bitrix_lead_payload or {}
        if workflow.bitrix_lead_id:
            try:
                lead = await bitrix.get_lead(workflow.bitrix_lead_id)
            except Exception:
                logger.exception(
                    "Could not refresh Bitrix lead %s for Paymob method resolution",
                    workflow.bitrix_lead_id,
                )
        return await resolve_paymob_payment_method_ids_async(
            lead,
            installment_number=number,
            settings=self.settings,
            bitrix=bitrix,
        )

    async def _is_tabby_mode(
        self,
        workflow: CustomerWorkflow,
        *,
        installment_number: int | None,
        allow_cross_installment_fallback: bool = True,
    ) -> bool:
        from app.services.payment_mode import (
            payment_mode_field_for_installment,
            resolve_is_tabby_payment_mode,
        )

        bitrix = get_bitrix_client(self.settings)
        snapshot = workflow.bitrix_lead_payload or {}
        lead: dict = dict(snapshot) if isinstance(snapshot, dict) else {}
        if workflow.bitrix_lead_id:
            try:
                fetched = await bitrix.get_lead(workflow.bitrix_lead_id)
                if isinstance(fetched, dict) and fetched:
                    # Prefer live lead, but keep payment-mode UFs from snapshot when
                    # the fetch omits them (common in mocks / partial CRM responses).
                    merged = dict(fetched)
                    for n in (1, 2, 3, 4):
                        field = payment_mode_field_for_installment(self.settings, n)
                        if field and not merged.get(field) and lead.get(field):
                            merged[field] = lead[field]
                    lead = merged
            except Exception:
                logger.exception(
                    "Could not refresh Bitrix lead %s for Tabby mode check",
                    workflow.bitrix_lead_id,
                )
        return await resolve_is_tabby_payment_mode(
            lead if isinstance(lead, dict) else {},
            installment_number=installment_number or 1,
            settings=self.settings,
            bitrix=bitrix,
            allow_cross_installment_fallback=allow_cross_installment_fallback,
        )

    async def _is_tamara_mode(
        self,
        workflow: CustomerWorkflow,
        *,
        installment_number: int | None,
        allow_cross_installment_fallback: bool = True,
    ) -> bool:
        from app.services.payment_mode import (
            payment_mode_field_for_installment,
            resolve_is_tamara_payment_mode,
        )

        bitrix = get_bitrix_client(self.settings)
        snapshot = workflow.bitrix_lead_payload or {}
        lead: dict = dict(snapshot) if isinstance(snapshot, dict) else {}
        if workflow.bitrix_lead_id:
            try:
                fetched = await bitrix.get_lead(workflow.bitrix_lead_id)
                if isinstance(fetched, dict) and fetched:
                    merged = dict(fetched)
                    for n in (1, 2, 3, 4):
                        field = payment_mode_field_for_installment(self.settings, n)
                        if field and not merged.get(field) and lead.get(field):
                            merged[field] = lead[field]
                    lead = merged
            except Exception:
                logger.exception(
                    "Could not refresh Bitrix lead %s for Tamara mode check",
                    workflow.bitrix_lead_id,
                )
        return await resolve_is_tamara_payment_mode(
            lead if isinstance(lead, dict) else {},
            installment_number=installment_number or 1,
            settings=self.settings,
            bitrix=bitrix,
            allow_cross_installment_fallback=allow_cross_installment_fallback,
        )

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

    def describe_inactive_token(self, token: str) -> str:
        """Human-readable reason when a payment link cannot be opened."""
        session = self.get_session_by_token(token)
        if not session:
            return (
                "This payment link is not recognized. It may be incomplete, from another "
                "environment, or was never created successfully."
            )
        if session.status == SESSION_COMPLETED:
            return (
                "This payment link was already used and completed. "
                "Ask your sales contact if a new link is needed."
            )
        if session.status == SESSION_EXPIRED or _ensure_utc(session.expires_at) <= _utcnow():
            if session.status != SESSION_EXPIRED:
                session.status = SESSION_EXPIRED
                self.db.commit()
            return (
                "This payment link has expired or was replaced by a newer link. "
                "Ask your sales contact to move the lead to the payment stage again "
                "for a fresh link."
            )
        return "This payment link is not available right now."

    def get_active_session_for_workflow(self, workflow: CustomerWorkflow) -> PaymentSession | None:
        sessions = self.db.scalars(
            select(PaymentSession)
            .where(
                PaymentSession.workflow_id == workflow.id,
                PaymentSession.status.in_((SESSION_PENDING, SESSION_TERMS_ACCEPTED)),
            )
            .order_by(PaymentSession.created_at.desc())
        ).all()
        for session in sessions:
            if _ensure_utc(session.expires_at) <= _utcnow():
                session.status = SESSION_EXPIRED
                continue
            return session
        self.db.commit()
        return None

    def expire_active_sessions_for_workflow(
        self,
        workflow: CustomerWorkflow,
        *,
        exclude_channels: set[str] | None = None,
    ) -> int:
        """Mark pending/terms-accepted sessions expired (e.g. switching to Cash)."""
        skip = {c.strip().lower() for c in (exclude_channels or set()) if c}
        sessions = list(
            self.db.scalars(
                select(PaymentSession).where(
                    PaymentSession.workflow_id == workflow.id,
                    PaymentSession.status.in_((SESSION_PENDING, SESSION_TERMS_ACCEPTED)),
                )
            ).all()
        )
        count = 0
        for session in sessions:
            channel = (getattr(session, "channel", None) or CHANNEL_ONLINE).strip().lower()
            if channel in skip:
                continue
            session.status = SESSION_EXPIRED
            count += 1
        if count:
            self.db.commit()
        return count

    async def get_or_create_reusable_session(
        self,
        workflow: CustomerWorkflow,
        *,
        charge_amount: Decimal | None = None,
        charge_source: str = "full",
        amount_locked: bool = True,
        installment_number: int | None = None,
        channel: str = CHANNEL_ONLINE,
    ) -> PaymentSession:
        """Reuse a non-expired payment session when charge amount still matches."""
        expected = charge_amount
        if expected is None:
            expected = workflow.remaining_balance if workflow.amount_paid > 0 else workflow.total_amount
        if expected <= 0 and workflow.total_amount > 0:
            expected = workflow.total_amount
        expected = Decimal(expected).quantize(Decimal("0.01"))
        channel = (channel or CHANNEL_ONLINE).strip().lower() or CHANNEL_ONLINE

        existing = self.get_active_session_for_workflow(workflow)
        if (
            existing
            and existing.charge_amount == expected
            and (existing.charge_source or "full") == charge_source
            and existing.installment_number == installment_number
            and (getattr(existing, "channel", None) or CHANNEL_ONLINE) == channel
        ):
            return existing
        replaced_old = False
        if existing:
            existing.status = SESSION_EXPIRED
            self.db.commit()
            replaced_old = True

        if workflow.finance_deal_id:
            source_type, source_id = self.source_finance_deal(workflow.finance_deal_id)
        else:
            source_type, source_id = self.source_lead(workflow.bitrix_lead_id)
        session = await self.create_session(
            workflow,
            source_type=source_type,
            source_id=source_id,
            charge_amount=expected,
            charge_source=charge_source,
            amount_locked=amount_locked,
            installment_number=installment_number,
            channel=channel,
        )
        # Mark so callers know Bitrix must be updated with the replacement URL.
        session._replaced_previous_link = replaced_old  # type: ignore[attr-defined]
        return session

    async def create_session(
        self,
        workflow: CustomerWorkflow,
        *,
        source_type: str,
        source_id: int,
        charge_amount: Decimal | None = None,
        charge_source: str = "full",
        amount_locked: bool = True,
        installment_number: int | None = None,
        channel: str = CHANNEL_ONLINE,
    ) -> PaymentSession:
        amount = charge_amount
        if amount is None:
            amount = workflow.remaining_balance if workflow.amount_paid > 0 else workflow.total_amount
        if amount <= 0 and workflow.total_amount > 0:
            amount = workflow.total_amount
        amount = Decimal(amount).quantize(Decimal("0.01"))
        channel = (channel or CHANNEL_ONLINE).strip().lower() or CHANNEL_ONLINE

        merchant_reference = f"WF-{workflow.id}-{uuid.uuid4().hex[:8]}"
        paymob_session_id = None
        paymob_checkout_url = None
        # Online Card/website → Paymob Intention now.
        # Tabby / Tamara skip Paymob; checkout is created on terms accept via their APIs.
        if channel not in (CHANNEL_BANK_TRANSFER, CHANNEL_CASH):
            allow_fb = (installment_number or 1) <= 1
            use_tabby = await self._is_tabby_mode(
                workflow,
                installment_number=installment_number,
                allow_cross_installment_fallback=allow_fb,
            )
            use_tamara = (
                False
                if use_tabby
                else await self._is_tamara_mode(
                    workflow,
                    installment_number=installment_number,
                    allow_cross_installment_fallback=allow_fb,
                )
            )
            if use_tabby or use_tamara:
                logger.info(
                    "Skipping Paymob Intention for %s mode | workflow=%s installment=%s",
                    "Tabby" if use_tabby else "Tamara",
                    workflow.id,
                    installment_number or 1,
                )
            else:
                paymob_session = await self._create_paymob_session(
                    workflow,
                    amount=amount,
                    currency=workflow.currency,
                    merchant_reference=merchant_reference,
                    trigger="new payment session",
                    installment_number=installment_number,
                )
                paymob_session_id = paymob_session.session_id
                paymob_checkout_url = paymob_session.checkout_url

        token = secrets.token_urlsafe(32)
        session = PaymentSession(
            workflow_id=workflow.id,
            token=token,
            source_type=source_type,
            source_id=source_id,
            charge_amount=amount,
            charge_source=charge_source,
            amount_locked=amount_locked,
            installment_number=installment_number,
            currency=workflow.currency,
            channel=channel,
            paymob_session_id=paymob_session_id,
            paymob_checkout_url=paymob_checkout_url,
            merchant_reference=merchant_reference,
            status=SESSION_PENDING,
            expires_at=_utcnow() + timedelta(hours=self.settings.payment_session_ttl_hours),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    async def refresh_paymob_checkout(
        self,
        session: PaymentSession,
        *,
        amount: Decimal | None = None,
    ) -> str:
        channel = (getattr(session, "channel", None) or CHANNEL_ONLINE).strip().lower()
        if channel in (CHANNEL_BANK_TRANSFER, CHANNEL_CASH):
            raise ValueError(f"{channel} sessions do not use Paymob checkout")
        workflow = session.workflow
        if amount is not None:
            session.charge_amount = amount
        new_reference = f"WF-{workflow.id}-{uuid.uuid4().hex[:8]}"
        paymob_session = await self._create_paymob_session(
            workflow,
            amount=session.charge_amount,
            currency=session.currency,
            merchant_reference=new_reference,
            trigger="payment link refresh",
            installment_number=getattr(session, "installment_number", None),
            payment_method_ids=await self._resolve_paymob_methods(
                workflow,
                installment_number=getattr(session, "installment_number", None),
            ),
        )
        session.merchant_reference = new_reference
        session.paymob_session_id = paymob_session.session_id
        session.paymob_checkout_url = paymob_session.checkout_url
        session.tabby_payment_id = None
        session.tamara_order_id = None
        self.db.commit()
        self.db.refresh(session)
        return session.paymob_checkout_url

    async def refresh_tabby_checkout(
        self,
        session: PaymentSession,
        *,
        amount: Decimal | None = None,
    ) -> str:
        """Create a Tabby HPP session and store payment id + web_url."""
        channel = (getattr(session, "channel", None) or CHANNEL_ONLINE).strip().lower()
        if channel in (CHANNEL_BANK_TRANSFER, CHANNEL_CASH):
            raise ValueError(f"{channel} sessions do not use Tabby checkout")
        workflow = session.workflow
        if amount is not None:
            session.charge_amount = amount
        new_reference = f"WF-{workflow.id}-{uuid.uuid4().hex[:8]}"
        item_title = "Course payment"
        pricing = workflow.pricing_snapshot or {}
        lines = pricing.get("lines") if isinstance(pricing, dict) else None
        if isinstance(lines, list) and lines:
            first = lines[0] if isinstance(lines[0], dict) else {}
            name = (first.get("name") or first.get("product_name") or "").strip()
            if name:
                item_title = name
        try:
            tabby_session = await self.tabby.create_checkout_session(
                amount=session.charge_amount,
                currency=session.currency or workflow.currency or "AED",
                merchant_reference=new_reference,
                customer_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                customer_phone=workflow.customer_phone,
                item_title=item_title,
            )
        except ValueError as exc:
            msg = str(exc)
            if "Tabby" in msg:
                from app.services.workflow_orchestrator import WorkflowOrchestrator

                orchestrator = WorkflowOrchestrator(self.db, self.settings)
                try:
                    await orchestrator.notify_paymob_link_failure(
                        workflow,
                        reason=msg,
                        trigger="Tabby checkout",
                    )
                except Exception:
                    logger.exception(
                        "Failed to notify Bitrix about Tabby error for lead %s",
                        workflow.bitrix_lead_id,
                    )
            raise

        session.merchant_reference = new_reference
        session.tabby_payment_id = tabby_session.payment_id
        session.tamara_order_id = None
        session.paymob_session_id = tabby_session.session_id or tabby_session.payment_id
        session.paymob_checkout_url = tabby_session.checkout_url
        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            self._reraise_if_bnpl_schema_missing(exc)
            raise
        self.db.refresh(session)
        return session.paymob_checkout_url

    async def refresh_tamara_checkout(
        self,
        session: PaymentSession,
        *,
        amount: Decimal | None = None,
    ) -> str:
        """Create a Tamara HPP session and store order id + checkout_url."""
        channel = (getattr(session, "channel", None) or CHANNEL_ONLINE).strip().lower()
        if channel in (CHANNEL_BANK_TRANSFER, CHANNEL_CASH):
            raise ValueError(f"{channel} sessions do not use Tamara checkout")
        workflow = session.workflow
        if amount is not None:
            session.charge_amount = amount
        new_reference = f"WF-{workflow.id}-{uuid.uuid4().hex[:8]}"
        item_title = "Course payment"
        pricing = workflow.pricing_snapshot or {}
        lines = pricing.get("lines") if isinstance(pricing, dict) else None
        if isinstance(lines, list) and lines:
            first = lines[0] if isinstance(lines[0], dict) else {}
            name = (first.get("name") or first.get("product_name") or "").strip()
            if name:
                item_title = name
        try:
            tamara_session = await self.tamara.create_checkout_session(
                amount=session.charge_amount,
                currency=session.currency or workflow.currency or "AED",
                merchant_reference=new_reference,
                customer_email=workflow.customer_email,
                customer_name=workflow.customer_name,
                customer_phone=workflow.customer_phone,
                item_title=item_title,
            )
        except ValueError as exc:
            msg = str(exc)
            if "Tamara" in msg:
                from app.services.workflow_orchestrator import WorkflowOrchestrator

                orchestrator = WorkflowOrchestrator(self.db, self.settings)
                try:
                    await orchestrator.notify_paymob_link_failure(
                        workflow,
                        reason=msg,
                        trigger="Tamara checkout",
                    )
                except Exception:
                    logger.exception(
                        "Failed to notify Bitrix about Tamara error for lead %s",
                        workflow.bitrix_lead_id,
                    )
            raise

        session.merchant_reference = new_reference
        session.tamara_order_id = tamara_session.order_id
        session.tabby_payment_id = None
        session.paymob_session_id = (
            tamara_session.checkout_id or tamara_session.order_id
        )
        session.paymob_checkout_url = tamara_session.checkout_url
        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            self._reraise_if_bnpl_schema_missing(exc)
            raise
        self.db.refresh(session)
        return session.paymob_checkout_url

    @staticmethod
    def _reraise_if_bnpl_schema_missing(exc: Exception) -> None:
        """Turn missing Alembic 024/025 columns into a clear operator error."""
        text = str(exc).lower()
        if "tabby_payment_id" in text or "tamara_order_id" in text:
            raise ValueError(
                "Database is missing BNPL columns (tabby_payment_id / tamara_order_id). "
                "Deploy must run Alembic migrations 024+025: alembic upgrade head"
            ) from exc

    def build_receipt_upload_url(self, token: str) -> str:
        base = self.settings.payment_frontend_base_url or self.settings.public_base_url
        return f"{base.rstrip('/')}/payment/{token}/receipt"

    def build_cash_thank_you_url(
        self,
        session: PaymentSession,
        *,
        name: str | None = None,
    ) -> str:
        from urllib.parse import urlencode

        base = self.settings.payment_frontend_base_url or self.settings.public_base_url
        qs = urlencode(
            {
                "kind": "cash",
                "amount": str(session.charge_amount),
                "currency": session.currency or "AED",
                "name": (name or "").strip(),
            }
        )
        return f"{base.rstrip('/')}/payment/thank-you?{qs}"

    def mark_terms_accepted(self, session: PaymentSession) -> None:
        session.status = SESSION_TERMS_ACCEPTED
        self.db.commit()

    def mark_completed(self, session: PaymentSession) -> None:
        session.status = SESSION_COMPLETED
        session.completed_at = _utcnow()
        self.db.commit()

    def build_payment_url(self, token: str) -> str:
        base = self.settings.payment_frontend_base_url or self.settings.public_base_url
        return f"{base.rstrip('/')}/payment/{token}"

    @staticmethod
    def source_lead(lead_id: int) -> tuple[str, int]:
        return SOURCE_LEAD, lead_id

    @staticmethod
    def source_finance_deal(deal_id: int) -> tuple[str, int]:
        return SOURCE_FINANCE_DEAL, deal_id
