"""Payment threshold evaluation and Bitrix stage unlock."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.base import PaymentSummary
from app.integrations.factory import get_bitrix_client
from app.models.customer_workflow import (
    STATUS_PAID,
    STATUS_THRESHOLD_MET,
    CustomerWorkflow,
)

logger = logging.getLogger(__name__)


class PaymentThresholdService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self.bitrix = get_bitrix_client(self.settings)

    def refresh_status(self, workflow: CustomerWorkflow) -> str:
        status = workflow.derive_payment_status(self.settings.payment_required_percent)
        workflow.payment_status = status
        if status in (STATUS_THRESHOLD_MET, STATUS_PAID) and workflow.threshold_met_at is None:
            workflow.threshold_met_at = datetime.now(timezone.utc)
        if status in (STATUS_THRESHOLD_MET, STATUS_PAID):
            workflow.reminders_enabled = False
        return status

    async def apply_after_payment(
        self,
        workflow: CustomerWorkflow,
        *,
        latest_transaction_id: str | None,
    ) -> PaymentSummary:
        status = self.refresh_status(workflow)
        percentage = workflow.payment_percentage()
        summary = PaymentSummary(
            total_amount=workflow.total_amount,
            amount_paid=workflow.amount_paid,
            remaining_balance=workflow.remaining_balance,
            currency=workflow.currency,
            latest_transaction_id=latest_transaction_id,
            payment_percentage=percentage,
            payment_status=status,
        )

        deal_ids = [workflow.sales_deal_id, workflow.finance_deal_id, workflow.b2c_deal_id]
        for deal_id in deal_ids:
            if not deal_id:
                continue
            try:
                await self.bitrix.update_deal_payment_summary(deal_id, summary)
            except Exception:
                logger.exception("Failed to update payment summary on deal %s", deal_id)

        if status in (STATUS_THRESHOLD_MET, STATUS_PAID) and self.settings.bitrix_finance_threshold_met_stage_id:
            if workflow.finance_deal_id:
                try:
                    await self.bitrix.set_deal_stage(
                        workflow.finance_deal_id,
                        self.settings.bitrix_finance_threshold_met_stage_id,
                    )
                    logger.info(
                        "Finance deal %s moved to stage %s (paid %s%%)",
                        workflow.finance_deal_id,
                        self.settings.bitrix_finance_threshold_met_stage_id,
                        percentage,
                    )
                except Exception:
                    logger.exception("Failed to unlock finance deal %s", workflow.finance_deal_id)

        self.db.commit()
        self.db.refresh(workflow)
        return summary
