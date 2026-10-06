"""Pause post-payment Bitrix and invoice work until a finance manager releases it."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.app_setting import KEY_FINANCE_MANAGER_VERIFICATION, AppSetting
from app.models.customer_workflow import CustomerWorkflow
from app.models.finance_verification import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    FinanceVerification,
)
from app.models.payment_transaction import PaymentTransaction
from app.models.staff_user import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_MANAGER, StaffUser

logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class FinanceVerificationService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def is_enabled(self) -> bool:
        """DB value wins after someone uses the admin switch. Otherwise the env default."""
        row = self.db.get(AppSetting, KEY_FINANCE_MANAGER_VERIFICATION)
        if row is None:
            return bool(self.settings.finance_manager_verification)
        return _truthy(row.value)

    def set_enabled(self, enabled: bool, staff: StaffUser) -> bool:
        row = self.db.get(AppSetting, KEY_FINANCE_MANAGER_VERIFICATION)
        if row is None:
            row = AppSetting(key=KEY_FINANCE_MANAGER_VERIFICATION, value="")
            self.db.add(row)
        row.value = "true" if enabled else "false"
        row.updated_by_id = staff.id
        row.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(
            "Finance manager verification %s by %s",
            "on" if enabled else "off",
            staff.email,
        )
        return enabled

    def hold_if_required(
        self,
        workflow: CustomerWorkflow,
        transaction: PaymentTransaction,
        *,
        amount: Decimal,
        currency: str,
        comment_prefix: str,
        skip_zoho: bool,
        skip_deals: bool,
        finance_release: bool,
        dev_simulate: bool,
    ) -> bool:
        """Return True when side effects must wait. Money is already recorded by the caller."""
        if transaction.id is None:
            self.db.flush()
        existing = self.db.scalar(
            select(FinanceVerification).where(
                FinanceVerification.payment_transaction_id == transaction.id
            )
        )
        if existing is not None:
            if existing.status == STATUS_PENDING or existing.status == STATUS_REJECTED:
                return True
            return False
        if finance_release or dev_simulate or not self.is_enabled():
            return False
        row = FinanceVerification(
            payment_transaction_id=transaction.id,
            workflow_id=workflow.id,
            bitrix_lead_id=workflow.bitrix_lead_id,
            customer_name=workflow.customer_name,
            channel=(transaction.source_type or "online"),
            amount=str(Decimal(amount).quantize(Decimal("0.01"))),
            currency=currency or workflow.currency or "AED",
            comment_prefix=comment_prefix or "Payment successful",
            skip_zoho=skip_zoho,
            skip_deals=skip_deals,
            status=STATUS_PENDING,
        )
        self.db.add(row)
        self.db.commit()
        logger.info(
            "Finance verification queued | txn=%s lead=%s amount=%s",
            transaction.id,
            workflow.bitrix_lead_id,
            row.amount,
        )
        return True

    def list_items(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        stmt = select(FinanceVerification).order_by(FinanceVerification.id.desc())
        if status:
            stmt = stmt.where(FinanceVerification.status == status)
        stmt = stmt.limit(max(1, min(limit, 500)))
        rows = list(self.db.scalars(stmt).all())
        names: dict[int, str] = {}
        decider_ids = {r.decided_by_id for r in rows if r.decided_by_id}
        if decider_ids:
            for user in self.db.scalars(select(StaffUser).where(StaffUser.id.in_(decider_ids))):
                names[user.id] = user.name
        return [self._to_dict(r, names.get(r.decided_by_id or 0)) for r in rows]

    def counts(self) -> dict[str, int]:
        pending = self.db.scalar(
            select(func.count())
            .select_from(FinanceVerification)
            .where(FinanceVerification.status == STATUS_PENDING)
        )
        return {"pending": int(pending or 0)}

    async def decide(self, verification_id: int, *, staff: StaffUser, approve: bool, note: str | None) -> dict[str, Any]:
        row = self.db.get(FinanceVerification, verification_id)
        if row is None:
            raise ValueError("Verification not found")
        if row.status != STATUS_PENDING:
            raise ValueError(f"Already {row.status}")
        row.status = STATUS_APPROVED if approve else STATUS_REJECTED
        row.decision_note = (note or "").strip() or None
        row.decided_by_id = staff.id
        row.decided_at = datetime.now(timezone.utc)
        self.db.commit()
        if approve:
            from app.services.workflow_orchestrator import WorkflowOrchestrator

            workflow = self.db.get(CustomerWorkflow, row.workflow_id)
            transaction = self.db.get(PaymentTransaction, row.payment_transaction_id)
            if workflow is None or transaction is None:
                raise ValueError("Payment record is missing")
            await WorkflowOrchestrator(self.db, self.settings).apply_recorded_payment(
                workflow,
                transaction,
                amount=Decimal(row.amount),
                currency=row.currency,
                comment_prefix=row.comment_prefix,
                skip_zoho=row.skip_zoho,
                skip_deals=row.skip_deals,
                finance_release=True,
            )
        self.db.refresh(row)
        return self._to_dict(row, staff.name)

    def staff_counts(self) -> dict[str, int]:
        out = {ROLE_ADMIN: 0, ROLE_MANAGER: 0, ROLE_EMPLOYEE: 0}
        rows = self.db.execute(
            select(StaffUser.role, func.count())
            .where(StaffUser.is_active.is_(True))
            .group_by(StaffUser.role)
        ).all()
        for role, count in rows:
            out[str(role)] = int(count)
        return out

    @staticmethod
    def _to_dict(row: FinanceVerification, decided_by_name: str | None) -> dict[str, Any]:
        return {
            "id": row.id,
            "payment_transaction_id": row.payment_transaction_id,
            "workflow_id": row.workflow_id,
            "bitrix_lead_id": row.bitrix_lead_id,
            "customer_name": row.customer_name,
            "channel": row.channel,
            "amount": row.amount,
            "currency": row.currency,
            "status": row.status,
            "decision_note": row.decision_note,
            "decided_by_name": decided_by_name,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
