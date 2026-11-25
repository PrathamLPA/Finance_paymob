"""Make the steps after a payment resumable, so a failure or a restart never loses them.

Saving the money is quick and certain. What follows (Bitrix comments, the Zoho invoice,
the email, the next-stage trigger) calls other systems and can fail halfway. Each step
that finishes is written to the transaction row, so running the follow-up again carries
on from where it stopped instead of repeating work (a second invoice payment, a second
comment, a second trigger).

`recover_unfinished` is the safety net: it finds follow-ups that were cut off by a
restart, or that hit a problem, and resumes them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, update

from app.models.payment_transaction import PaymentTransaction

logger = logging.getLogger(__name__)

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_PROBLEM = "problem"

# A follow-up still "running" after this long was cut off (restart / crash).
ORPHAN_AFTER = timedelta(seconds=90)
# A follow-up that hit a problem is tried again, a few times, after this pause.
RETRY_AFTER = timedelta(minutes=5)
MAX_ATTEMPTS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class Checkpoints:
    """Which follow-up steps already finished for one payment (stored on the row)."""

    def __init__(self, db, transaction: PaymentTransaction, *, enabled: bool = True):
        self.db = db
        self.txn = transaction
        self.enabled = enabled

    def _data(self) -> dict[str, Any]:
        raw = self.txn.post_steps
        return dict(raw) if isinstance(raw, dict) else {}

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self._data().get("meta") or {})

    def set_meta(self, **values: Any) -> None:
        if not self.enabled:
            return
        data = self._data()
        data["meta"] = {**(data.get("meta") or {}), **values}
        self.txn.post_steps = data
        self.db.commit()

    def done(self, name: str) -> bool:
        return self.enabled and name in (self._data().get("done") or {})

    def mark(self, name: str) -> None:
        if not self.enabled:
            return
        data = self._data()
        data["done"] = {**(data.get("done") or {}), name: _now().isoformat()}
        self.txn.post_steps = data
        self.db.commit()


def mark_running(db, transaction: PaymentTransaction) -> None:
    """Record that the follow-up has started, before it is handed to the background."""
    transaction.post_state = STATE_RUNNING
    transaction.post_attempts = int(transaction.post_attempts or 0) + 1
    transaction.post_updated_at = _now()
    db.commit()


def record_outcome(db, transaction: PaymentTransaction, problems: list[str]) -> None:
    transaction.post_state = STATE_PROBLEM if problems else STATE_DONE
    transaction.post_problems = list(problems) or None
    transaction.post_updated_at = _now()
    db.commit()


def follow_up_summary(transaction: PaymentTransaction) -> dict[str, Any]:
    """What the screens show about a payment's follow-up work."""
    return {
        "state": transaction.post_state or "",
        "problems": list(transaction.post_problems or []),
        "attempts": int(transaction.post_attempts or 0),
    }


async def resume(transaction_id: int, settings) -> list[str]:
    """Run the unfinished follow-up steps for one payment, skipping finished ones."""
    from app.models.customer_workflow import CustomerWorkflow
    from app.services import background_jobs
    from app.services.workflow_orchestrator import WorkflowOrchestrator

    with background_jobs.open_session() as db:
        txn = db.get(PaymentTransaction, transaction_id)
        if txn is None:
            return ["The payment record could not be found"]
        workflow = db.get(CustomerWorkflow, txn.workflow_id)
        if workflow is None:
            return ["The customer record could not be found"]
        meta = (txn.post_steps or {}).get("meta") or {}
        orchestrator = WorkflowOrchestrator(db, settings)
        try:
            await orchestrator.apply_recorded_payment(
                workflow,
                txn,
                amount=Decimal(str(meta.get("amount") or txn.amount)),
                currency=str(meta.get("currency") or txn.currency),
                comment_prefix=str(meta.get("comment_prefix") or "Payment successful"),
                skip_zoho=bool(meta.get("skip_zoho")),
                skip_deals=bool(meta.get("skip_deals")),
                finance_release=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Resumed follow-up crashed | txn=%s", transaction_id)
            db.rollback()
            record_outcome(db, txn, [f"{type(exc).__name__}: {exc}"[:200]])
            return list(txn.post_problems or [])
        return orchestrator.last_problems


def start_resume(transaction_id: int, settings, *, label: str) -> str:
    """Resume a payment's follow-up in the background and return its job key."""
    from app.services import background_jobs

    with background_jobs.open_session() as db:
        txn = db.get(PaymentTransaction, transaction_id)
        if txn is not None:
            mark_running(db, txn)
    key = f"payment:{transaction_id}"

    async def _run() -> list[str]:
        return await resume(transaction_id, settings)

    background_jobs.spawn(key, label, _run)
    return key


async def recover_unfinished(settings) -> int:
    """Resume follow-ups cut off by a restart, and retry ones that hit a problem."""
    from app.services import background_jobs

    now = _now()
    resumed = 0
    with background_jobs.open_session() as db:
        candidates = list(
            db.scalars(
                select(PaymentTransaction).where(
                    or_(
                        PaymentTransaction.post_state == STATE_RUNNING,
                        PaymentTransaction.post_state == STATE_PROBLEM,
                    )
                )
            )
        )
        for txn in candidates:
            key = f"payment:{txn.id}"
            live = background_jobs.get_job(key)
            if live is not None and live.state == background_jobs.STATE_RUNNING:
                continue  # still being worked on in this process
            last = _aware(txn.post_updated_at) or now
            attempts = int(txn.post_attempts or 0)
            if txn.post_state == STATE_RUNNING:
                due = now - last > ORPHAN_AFTER
            else:
                due = attempts < MAX_ATTEMPTS and now - last > RETRY_AFTER
            if not due or not (txn.post_steps or {}).get("meta"):
                continue
            # Claim it atomically so two servers never resume the same payment.
            claimed = db.execute(
                update(PaymentTransaction)
                .where(
                    PaymentTransaction.id == txn.id,
                    PaymentTransaction.post_updated_at == txn.post_updated_at,
                )
                .values(
                    post_state=STATE_RUNNING,
                    post_attempts=attempts + 1,
                    post_updated_at=now,
                )
            )
            db.commit()
            if not claimed.rowcount:
                continue
            logger.warning(
                "Resuming unfinished payment follow-up | txn=%s state=%s attempts=%s",
                txn.id,
                txn.post_state,
                attempts + 1,
            )
            txn_id = txn.id

            async def _run(txn_id=txn_id) -> list[str]:
                return await resume(txn_id, settings)

            background_jobs.spawn(key, f"Resumed follow-up for payment {txn_id}", _run)
            resumed += 1
    return resumed


async def recovery_loop(settings, *, first_delay: float = 20.0, every: float = 120.0) -> None:
    """Run `recover_unfinished` shortly after startup and then every couple of minutes."""
    await asyncio.sleep(first_delay)
    while True:
        try:
            resumed = await recover_unfinished(settings)
            if resumed:
                logger.info("Recovered %s unfinished payment follow-up(s)", resumed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Payment follow-up recovery pass failed")
        await asyncio.sleep(every)
