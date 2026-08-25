"""Due-date installment emails for clients."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services.installment_charge import _field, _money

DUBAI_TZ = ZoneInfo("Asia/Dubai")


@dataclass(frozen=True)
class InstallmentSlot:
    number: int
    due_date: date
    amount: Decimal | None


def today_in_dubai() -> date:
    return datetime.now(DUBAI_TZ).date()


def parse_bitrix_date(value: Any) -> date | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, dict):
        value = value.get("VALUE") or value.get("value") or value.get("date")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(DUBAI_TZ).date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit() and len(raw) >= 10:
        try:
            return datetime.fromtimestamp(int(raw[:10]), tz=timezone.utc).astimezone(DUBAI_TZ).date()
        except (OSError, OverflowError, ValueError):
            return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(DUBAI_TZ).date()
    except ValueError:
        return None


def installment_schedule(entity: dict[str, Any] | None, settings: Settings) -> list[InstallmentSlot]:
    entity = entity or {}
    slots = [
        (1, settings.bitrix_field_installment_1, settings.bitrix_field_installment_1_date),
        (2, settings.bitrix_field_installment_2, settings.bitrix_field_installment_2_due_date),
        (3, settings.bitrix_field_installment_3, settings.bitrix_field_installment_3_due_date),
        (4, settings.bitrix_field_installment_4, settings.bitrix_field_installment_4_due_date),
    ]
    count_raw = _field(entity, settings.bitrix_field_installment_count)
    try:
        count = int(str(count_raw).strip()) if count_raw not in (None, "") else None
    except (TypeError, ValueError):
        count = None

    schedule: list[InstallmentSlot] = []
    for number, amount_field, date_field in slots:
        if count is not None and number > count:
            break
        due = parse_bitrix_date(_field(entity, date_field)) if date_field else None
        amount = _money(_field(entity, amount_field)) if amount_field else None
        if due is None:
            continue
        schedule.append(InstallmentSlot(number=number, due_date=due, amount=amount))
    return schedule


def is_installment_plan(entity: dict[str, Any] | None, settings: Settings) -> bool:
    schedule = installment_schedule(entity, settings)
    if len(schedule) >= 2:
        return True
    count_raw = _field(entity or {}, settings.bitrix_field_installment_count)
    try:
        count = int(str(count_raw).strip()) if count_raw not in (None, "") else 0
    except (TypeError, ValueError):
        count = 0
    return count >= 2 and bool(schedule)


def next_due_installment(
    entity: dict[str, Any] | None,
    settings: Settings,
    *,
    amount_paid: Decimal,
    today: date | None = None,
) -> InstallmentSlot | None:
    """Earliest unpaid installment whose due date has arrived (Dubai date)."""
    today = today or today_in_dubai()
    paid = amount_paid or Decimal("0")
    cumulative = Decimal("0")
    for slot in installment_schedule(entity, settings):
        piece = slot.amount or Decimal("0")
        if piece > 0:
            cumulative += piece
            still_unpaid = paid < cumulative
        else:
            still_unpaid = True
        if not still_unpaid:
            continue
        if today >= slot.due_date:
            return slot
        return None
    return None
