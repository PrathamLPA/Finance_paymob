"""Bitrix payment-mode enum helpers (Cash / Online / Bank Transfer / …)."""

from __future__ import annotations

from typing import Any

from app.config import Settings


def _parse_mode_enum_map(settings: Settings) -> dict[str, str]:
    raw = (getattr(settings, "bitrix_payment_mode_enum_map", None) or "").strip()
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        enum_id, label = part.split(":", 1)
        out[enum_id.strip()] = label.strip().lower()
    return out


def cash_mode_enum_ids(settings: Settings) -> set[str]:
    raw = (getattr(settings, "cash_mode_enum_ids", None) or "5786").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def payment_mode_field_for_installment(settings: Settings, installment_number: int) -> str:
    mapping = {
        1: settings.bitrix_field_payment_1_mode,
        2: settings.bitrix_field_payment_2_mode,
        3: settings.bitrix_field_payment_3_mode,
        4: settings.bitrix_field_payment_4_mode,
    }
    return mapping.get(installment_number) or ""


def payment_mode_enum_id(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
) -> str | None:
    field = payment_mode_field_for_installment(settings, installment_number)
    if not field or not lead:
        return None
    value = lead.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None or value == "":
        return None
    return str(value).strip()


def payment_mode_label(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
) -> str | None:
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    if not enum_id:
        return None
    return _parse_mode_enum_map(settings).get(enum_id) or enum_id


def is_cash_payment_mode(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
) -> bool:
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    if not enum_id:
        return False
    return enum_id in cash_mode_enum_ids(settings)
