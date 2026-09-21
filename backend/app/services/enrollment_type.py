"""Lead enrollment type: Batch (catalog path) vs One-One (manager approval)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.config import Settings
from app.services.estimate_price_gate import PriceGateResult

ONE_ON_ONE_APPROVAL_REASON = (
    "Enrollment type is One-One. Manager approval is required before sending a "
    "payment link."
)


def _raw_enrollment_value(lead: dict[str, Any], settings: Settings) -> str:
    field = (settings.bitrix_field_enrollment_type or "").strip()
    if not field:
        return ""
    raw = lead.get(field)
    if raw is None and field.startswith("UF_"):
        # crm.item sometimes returns camelCase ufCrm…
        camel = "ufCrm" + field[6:]
        raw = lead.get(camel)
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, dict):
        raw = raw.get("VALUE") or raw.get("value") or raw.get("ID") or ""
    return str(raw or "").strip()


def is_one_on_one_enrollment(lead: dict[str, Any], settings: Settings) -> bool:
    """True when Bitrix enrollment type is One-One (not Batch / not selected)."""
    raw = _raw_enrollment_value(lead, settings)
    if not raw:
        return False
    one_ids = {
        part.strip()
        for part in (settings.bitrix_enrollment_one_one_enum_ids or "").split(",")
        if part.strip()
    }
    if raw in one_ids:
        return True
    return raw.casefold() in {"one - one", "one-one", "one_one", "one on one"}


def is_batch_enrollment(lead: dict[str, Any], settings: Settings) -> bool:
    raw = _raw_enrollment_value(lead, settings)
    if not raw:
        return False
    batch_ids = {
        part.strip()
        for part in (settings.bitrix_enrollment_batch_enum_ids or "").split(",")
        if part.strip()
    }
    if raw in batch_ids:
        return True
    return raw.casefold() in {"batch"}


def apply_enrollment_type_to_gate(
    gate: PriceGateResult,
    lead: dict[str, Any],
    settings: Settings,
) -> PriceGateResult:
    """Batch / blank → keep inventory gate. One-One → always require manager approval."""
    if not is_one_on_one_enrollment(lead, settings):
        return gate
    reason = ONE_ON_ONE_APPROVAL_REASON
    if gate.reason and not gate.ok:
        if ONE_ON_ONE_APPROVAL_REASON not in gate.reason:
            reason = f"{gate.reason}\n{ONE_ON_ONE_APPROVAL_REASON}"
        else:
            reason = gate.reason
    return replace(gate, ok=False, reason=reason)
