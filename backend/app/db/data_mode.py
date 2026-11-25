"""Test data versus production data.

Every payment record is stamped with the mode that was active when it was created.
Staff and admin screens only show the active mode, so switching to production starts
from zero and test records stay separate until someone switches back.

Webhooks and the customer payment pages are not filtered: a Paymob callback must
always find its session, whichever mode is on when it arrives.
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

logger = logging.getLogger(__name__)

MODE_TEST = "test"
MODE_LIVE = "live"

# Nothing is "live" until an admin turns production on, so a fresh deploy keeps
# behaving like the development setup it replaces.
DEFAULT_MODE = MODE_TEST

_CACHE_TTL_SECONDS = 5.0
_lock = threading.Lock()
_cache: dict[str, float | str | None] = {"value": None, "at": 0.0}


def reset_cache() -> None:
    with _lock:
        _cache["value"] = None
        _cache["at"] = 0.0


def _store(value: str) -> None:
    with _lock:
        _cache["value"] = value
        _cache["at"] = time.monotonic()


def current_data_mode() -> str:
    """The active mode. Falls back to test if the database cannot be read."""
    with _lock:
        value = _cache["value"]
        age = time.monotonic() - float(_cache["at"] or 0.0)
    if isinstance(value, str) and age < _CACHE_TTL_SECONDS:
        return value
    try:
        from app.db.session import SessionLocal
        from app.models.app_setting import KEY_DATA_MODE, AppSetting

        with SessionLocal() as db:
            row = db.get(AppSetting, KEY_DATA_MODE)
            mode = MODE_LIVE if row is not None and row.value == MODE_LIVE else DEFAULT_MODE
    except Exception:
        logger.warning("Could not read the data mode; assuming %s", DEFAULT_MODE, exc_info=True)
        return DEFAULT_MODE
    _store(mode)
    return mode


def set_data_mode(db: Session, mode: str, staff_id: int | None) -> str:
    from datetime import datetime, timezone

    from app.models.app_setting import KEY_DATA_MODE, AppSetting

    mode = MODE_LIVE if mode == MODE_LIVE else MODE_TEST
    row = db.get(AppSetting, KEY_DATA_MODE)
    if row is None:
        row = AppSetting(key=KEY_DATA_MODE, value="")
        db.add(row)
    row.value = mode
    row.updated_by_id = staff_id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    _store(mode)
    return mode


# Models stamped with data_mode. Filled in by register_filter() to avoid import cycles.
_FILTER_FLAG = "data_mode_filter"


def register_filter() -> None:
    """Hide the other mode's rows from any session flagged with enable_filter()."""
    from app.models.bank_transfer import BankTransferSubmission
    from app.models.cash_collection import CashCollection
    from app.models.cash_deposit import CashDeposit
    from app.models.customer_workflow import CustomerWorkflow
    from app.models.email_log import EmailLog
    from app.models.finance_verification import FinanceVerification
    from app.models.payment_session import PaymentSession
    from app.models.payment_transaction import PaymentTransaction

    models = (
        BankTransferSubmission,
        CashCollection,
        CashDeposit,
        CustomerWorkflow,
        EmailLog,
        FinanceVerification,
        PaymentSession,
        PaymentTransaction,
    )

    @event.listens_for(Session, "do_orm_execute")
    def _apply_mode_filter(state) -> None:  # noqa: ANN001
        if not state.is_select or not state.session.info.get(_FILTER_FLAG):
            return
        mode = current_data_mode()
        statement = state.statement
        for model in models:
            statement = statement.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.data_mode == mode,
                    include_aliases=True,
                    track_closure_variables=True,
                )
            )
        state.statement = statement


def enable_filter(db: Session) -> None:
    db.info[_FILTER_FLAG] = True
