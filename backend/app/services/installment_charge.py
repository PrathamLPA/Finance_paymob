"""Resolve how much the first payment link should charge from Bitrix installment fields."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any


CHARGE_SOURCE_INSTALLMENT_1 = "installment_1"
CHARGE_SOURCE_FULL = "full"


def _money(value: Any) -> Decimal | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, dict):
        value = value.get("VALUE") or value.get("value") or value.get("amount")
    try:
        amount = Decimal(str(value).replace(",", "").replace(" ", "").strip())
    except (InvalidOperation, ArithmeticError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _field(entity: dict[str, Any], field_code: str) -> Any:
    if not field_code:
        return None
    if field_code in entity:
        return entity.get(field_code)
    # Bitrix sometimes returns lowercase camelCase for SPA entities.
    lowered = {str(k).lower(): v for k, v in entity.items()}
    return lowered.get(field_code.lower())


@dataclass(frozen=True)
class ChargePlan:
    amount: Decimal
    source: str
    label: str
    locked: bool = True
    installment_count: int | None = None
    installment_1: Decimal | None = None


def resolve_first_charge(
    entity: dict[str, Any] | None,
    *,
    remaining_balance: Decimal,
    installment_1_field: str = "",
    installment_count_field: str = "",
) -> ChargePlan:
    """First payment link amount from Bitrix Payment Installment 1, else full balance.

    Installment 2/3/4 due-date scheduling is intentionally not handled here yet.
    """
    remaining = remaining_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if remaining <= 0:
        remaining = Decimal("0.00")

    entity = entity or {}
    installment_1 = _money(_field(entity, installment_1_field)) if installment_1_field else None
    count_raw = _field(entity, installment_count_field) if installment_count_field else None
    try:
        installment_count = int(str(count_raw).strip()) if count_raw not in (None, "") else None
    except (TypeError, ValueError):
        installment_count = None

    if installment_1 is not None and installment_1 > 0 and remaining > 0:
        amount = min(installment_1, remaining)
        return ChargePlan(
            amount=amount,
            source=CHARGE_SOURCE_INSTALLMENT_1,
            label="Installment 1",
            locked=True,
            installment_count=installment_count,
            installment_1=installment_1,
        )

    return ChargePlan(
        amount=remaining,
        source=CHARGE_SOURCE_FULL,
        label="Full payment",
        locked=True,
        installment_count=installment_count,
        installment_1=installment_1,
    )
