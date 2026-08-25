"""Capture and resolve persisted installment plans for first payment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.customer_workflow import CustomerWorkflow
from app.models.workflow_installment import WorkflowInstallment
from app.services.installment_charge import (
    CHARGE_SOURCE_FULL,
    CHARGE_SOURCE_INSTALLMENT_1,
    ChargePlan,
    _field,
    _money,
    resolve_first_charge,
)
from app.services.installment_notices import parse_bitrix_date


@dataclass(frozen=True)
class ParsedInstallment:
    number: int
    amount: Decimal | None
    due_date: date | None


@dataclass(frozen=True)
class PlanValidation:
    ok: bool
    indicated: bool
    slots: list[ParsedInstallment]
    errors: list[str]
    expected_count: int | None = None


def _installment_field_map(settings: Settings) -> list[tuple[int, str, str]]:
    return [
        (1, settings.bitrix_field_installment_1, settings.bitrix_field_installment_1_date),
        (2, settings.bitrix_field_installment_2, settings.bitrix_field_installment_2_due_date),
        (3, settings.bitrix_field_installment_3, settings.bitrix_field_installment_3_due_date),
        (4, settings.bitrix_field_installment_4, settings.bitrix_field_installment_4_due_date),
    ]


def _parse_count_enum_map(settings: Settings) -> dict[str, int]:
    """Map Bitrix list-field IDs → installment count (e.g. 5830 → 3)."""
    mapping: dict[str, int] = {}
    raw = (getattr(settings, "bitrix_installment_count_enum_map", None) or "").strip()
    if not raw:
        return mapping
    for part in raw.split(","):
        piece = part.strip()
        if not piece or ":" not in piece:
            continue
        enum_id, value = piece.split(":", 1)
        try:
            count = int(value.strip())
        except (TypeError, ValueError):
            continue
        if 1 <= count <= 4:
            mapping[enum_id.strip()] = count
    return mapping


def _installment_count(entity: dict[str, Any], settings: Settings) -> int | None:
    """Read Bitrix installment count (plain 1–4 or list-field enum ID)."""
    count_raw = _field(entity, settings.bitrix_field_installment_count)
    try:
        if count_raw in (None, ""):
            return None
        token = str(count_raw).strip().split(".")[0]
        count = int(token)
    except (TypeError, ValueError):
        return None
    if 1 <= count <= 4:
        return count
    # Bitrix enumeration fields return IDs like 5830 for display value "3".
    mapped = _parse_count_enum_map(settings).get(str(count))
    if mapped is not None:
        return mapped
    return None


def _derived_installment_count(
    entity: dict[str, Any],
    settings: Settings,
    candidates: list[ParsedInstallment] | None = None,
) -> int | None:
    count = _installment_count(entity, settings)
    if count is not None:
        return count
    slots = candidates if candidates is not None else parse_installment_candidates(entity, settings)
    if not slots:
        return None
    return max(s.number for s in slots)


def parse_installment_candidates(
    entity: dict[str, Any] | None,
    settings: Settings,
) -> list[ParsedInstallment]:
    entity = entity or {}
    count = _installment_count(entity, settings)
    slots: list[ParsedInstallment] = []
    for number, amount_field, date_field in _installment_field_map(settings):
        if count is not None and number > count:
            break
        amount = _money(_field(entity, amount_field)) if amount_field else None
        due = parse_bitrix_date(_field(entity, date_field)) if date_field else None
        if amount is None and due is None:
            continue
        slots.append(ParsedInstallment(number=number, amount=amount, due_date=due))
    return slots


def plan_is_indicated(entity: dict[str, Any] | None, settings: Settings) -> bool:
    """True when Bitrix data claims a multi-installment plan."""
    entity = entity or {}
    count = _derived_installment_count(entity, settings) or 0
    candidates = parse_installment_candidates(entity, settings)
    dated = [s for s in candidates if s.due_date is not None]
    if len(dated) >= 2:
        return True
    if count >= 2 and candidates:
        return True
    return False


def validate_installment_plan(
    entity: dict[str, Any] | None,
    settings: Settings,
    *,
    payable_total: Decimal,
) -> PlanValidation:
    entity = entity or {}
    indicated = plan_is_indicated(entity, settings)
    candidates = parse_installment_candidates(entity, settings)
    if not indicated:
        return PlanValidation(ok=True, indicated=False, slots=candidates, errors=[])

    count = _derived_installment_count(entity, settings, candidates)
    errors: list[str] = []
    expected = count
    if expected is None:
        expected = max((s.number for s in candidates), default=0)
    if expected < 2:
        errors.append("Installment plan needs at least 2 installments.")
        return PlanValidation(
            ok=False, indicated=True, slots=candidates, errors=errors, expected_count=expected
        )

    by_number = {s.number: s for s in candidates}
    slots: list[ParsedInstallment] = []
    for number in range(1, expected + 1):
        slot = by_number.get(number)
        if slot is None:
            errors.append(f"Installment {number} is missing amount and due date.")
            continue
        if slot.amount is None or slot.amount <= 0:
            errors.append(f"Installment {number} needs a positive amount.")
        if slot.due_date is None:
            errors.append(f"Installment {number} needs a due date.")
        slots.append(slot)

    complete = [
        s for s in slots if s.amount is not None and s.amount > 0 and s.due_date is not None
    ]
    for prev, nxt in zip(complete, complete[1:]):
        if prev.due_date and nxt.due_date and nxt.due_date < prev.due_date:
            errors.append(
                f"Installment {nxt.number} due date is before installment {prev.number}."
            )

    if len(complete) == expected:
        schedule_total = sum((s.amount or Decimal("0") for s in complete), Decimal("0"))
        schedule_total = schedule_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payable = payable_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if schedule_total != payable:
            errors.append(
                f"Installment amounts total {schedule_total:.2f} but payable total is "
                f"{payable:.2f}. They must match."
            )

    return PlanValidation(
        ok=not errors,
        indicated=True,
        slots=complete if not errors else candidates,
        errors=errors,
        expected_count=expected,
    )


def persist_installment_plan(
    db: Session,
    workflow: CustomerWorkflow,
    slots: list[ParsedInstallment],
    *,
    replace: bool = False,
) -> None:
    """Freeze installment rows once. Later Bitrix edits are ignored unless replace=True."""
    if workflow.installments and not replace:
        return
    if replace and workflow.installments:
        for row in list(workflow.installments):
            db.delete(row)
        db.flush()
    for slot in slots:
        if slot.amount is None or slot.due_date is None:
            continue
        db.add(
            WorkflowInstallment(
                workflow_id=workflow.id,
                installment_number=slot.number,
                amount=slot.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                due_date=slot.due_date,
            )
        )
    db.commit()
    db.refresh(workflow)
    db.expire(workflow, ["installments"])
    _ = workflow.installments



def resolve_first_charge_for_workflow(
    workflow: CustomerWorkflow,
    *,
    lead: dict[str, Any] | None,
    settings: Settings,
) -> ChargePlan:
    """Prefer persisted installment 1; otherwise fall back to live lead fields."""
    remaining = (workflow.remaining_balance or workflow.total_amount).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    persisted = sorted(workflow.installments or [], key=lambda row: row.installment_number)
    if persisted:
        first = persisted[0]
        amount = min(Decimal(first.amount), remaining) if remaining > 0 else Decimal("0.00")
        return ChargePlan(
            amount=amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            source=CHARGE_SOURCE_INSTALLMENT_1,
            label="Installment 1",
            locked=True,
            installment_count=len(persisted),
            installment_1=Decimal(first.amount),
        )

    return resolve_first_charge(
        lead or workflow.bitrix_lead_payload or {},
        remaining_balance=remaining,
        installment_1_field=settings.bitrix_field_installment_1,
        installment_count_field=settings.bitrix_field_installment_count,
    )


def installment_status_for_amount(
    *,
    installment_number: int,
    amount: Decimal,
    amount_paid: Decimal,
    cumulative_before: Decimal,
) -> str:
    paid_through = amount_paid
    slot_end = cumulative_before + amount
    if paid_through >= slot_end:
        return "paid"
    if paid_through > cumulative_before:
        return "partial"
    if installment_number == 1 or paid_through >= cumulative_before:
        return "due"
    return "upcoming"


def schedule_payload(workflow: CustomerWorkflow) -> list[dict[str, Any]]:
    rows = sorted(workflow.installments or [], key=lambda row: row.installment_number)
    payload: list[dict[str, Any]] = []
    cumulative = Decimal("0.00")
    paid = Decimal(workflow.amount_paid or 0).quantize(Decimal("0.01"))
    for row in rows:
        amount = Decimal(row.amount).quantize(Decimal("0.01"))
        status = installment_status_for_amount(
            installment_number=row.installment_number,
            amount=amount,
            amount_paid=paid,
            cumulative_before=cumulative,
        )
        payload.append(
            {
                "number": row.installment_number,
                "amount": str(amount),
                "due_date": row.due_date.isoformat(),
                "status": status,
            }
        )
        cumulative += amount
    return payload


@dataclass(frozen=True)
class InstallmentPolicyResult:
    needs_approval: bool
    reasons: list[str]
    installment_count: int | None
    installment_1: Decimal | None
    installment_1_percent: Decimal | None
    gap_days: int | None
    schedule: list[dict[str, str]]
    first_below_percent: bool = False
    count_above_two: bool = False
    gap_over_limit: bool = False
    missing_amounts: bool = False


def evaluate_installment_policy(
    entity: dict[str, Any] | None,
    settings: Settings,
    *,
    payable_total: Decimal,
    required_percent: float | None = None,
    max_gap_days: int = 30,
) -> InstallmentPolicyResult:
    """Manager approval when any installment policy rule fails.

    Rules (any one triggers):
    1. Installment 1 is less than required_percent of the payable total (default 50%)
    2. Installment count is greater than 2
    3. Installment 2 due date is more than max_gap_days after Installment 1 due date
    4. Any dated installment is missing its amount
    """
    entity = entity or {}
    threshold = Decimal(str(required_percent if required_percent is not None else settings.payment_required_percent))
    payable = payable_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    candidates = parse_installment_candidates(entity, settings)
    count = _derived_installment_count(entity, settings, candidates)

    installment_1 = None
    for slot in candidates:
        if slot.number == 1 and slot.amount is not None:
            installment_1 = slot.amount
            break
    if installment_1 is None:
        installment_1 = _money(_field(entity, settings.bitrix_field_installment_1))

    reasons: list[str] = []
    first_below = False
    count_above = False
    gap_over = False
    missing_amounts = False
    percent: Decimal | None = None

    if installment_1 is not None and payable > 0:
        percent = (installment_1 / payable * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if percent < threshold:
            first_below = True
            reasons.append(
                f"Installment 1 is {percent}% of the total "
                f"({installment_1:.2f} of {payable:.2f}), below the {threshold:g}% minimum."
            )

    if count is not None and count > 2:
        count_above = True
        reasons.append(
            f"Installment count is {count} (more than 2). Manager approval is required."
        )

    gap_days: int | None = None
    by_number = {s.number: s for s in candidates}
    first = by_number.get(1)
    second = by_number.get(2)
    if first and second and first.due_date and second.due_date:
        gap_days = (second.due_date - first.due_date).days
        if gap_days > max_gap_days:
            gap_over = True
            reasons.append(
                f"Next installment is due {gap_days} days after Installment 1 "
                f"(limit is {max_gap_days} days)."
            )

    for slot in candidates:
        if slot.due_date is not None and (slot.amount is None or slot.amount <= 0):
            missing_amounts = True
            reasons.append(
                f"Installment {slot.number} has a due date but no amount in Bitrix."
            )

    schedule = [
        {
            "number": str(s.number),
            "amount": str(s.amount) if s.amount is not None else "",
            "due_date": s.due_date.isoformat() if s.due_date else "",
            "amount_missing": "1" if (s.amount is None or s.amount <= 0) else "0",
        }
        for s in candidates
    ]
    return InstallmentPolicyResult(
        needs_approval=bool(reasons),
        reasons=reasons,
        installment_count=count,
        installment_1=installment_1,
        installment_1_percent=percent,
        gap_days=gap_days,
        schedule=schedule,
        first_below_percent=first_below,
        count_above_two=count_above,
        gap_over_limit=gap_over,
        missing_amounts=missing_amounts,
    )


def installment_policy_payload(result: InstallmentPolicyResult) -> dict[str, Any]:
    return {
        "needs_approval": result.needs_approval,
        "reasons": result.reasons,
        "installment_count": result.installment_count,
        "installment_1": str(result.installment_1) if result.installment_1 is not None else None,
        "installment_1_percent": (
            str(result.installment_1_percent) if result.installment_1_percent is not None else None
        ),
        "gap_days": result.gap_days,
        "schedule": result.schedule,
        "issues": {
            "first_below_percent": result.first_below_percent,
            "count_above_two": result.count_above_two,
            "gap_over_limit": result.gap_over_limit,
            "missing_amounts": result.missing_amounts,
        },
    }


def backfill_installment_plan_from_payload(
    db: Session,
    workflow: CustomerWorkflow,
    settings: Settings,
) -> bool:
    """Best-effort backfill for existing workflows. Returns True when persisted."""
    if workflow.installments:
        return True
    lead = workflow.bitrix_lead_payload or {}
    validation = validate_installment_plan(
        lead,
        settings,
        payable_total=Decimal(workflow.total_amount or 0),
    )
    if not validation.ok or not validation.indicated:
        return False
    persist_installment_plan(db, workflow, validation.slots)
    return bool(workflow.installments)
