"""Bitrix payment-mode enum helpers (Cash / Online / Bank Transfer / …)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


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


def _normalize_enum_value(value: Any) -> str | None:
    """Extract a Bitrix enumeration ID or label from common CRM shapes."""
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        return _normalize_enum_value(value[0])
    if isinstance(value, dict):
        for key in ("ID", "id", "VALUE", "value", "XML_ID", "xmlId"):
            nested = value.get(key)
            if nested is not None and nested != "":
                return _normalize_enum_value(nested)
        return None
    text = str(value).strip()
    return text or None


def payment_mode_enum_id(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
) -> str | None:
    field = payment_mode_field_for_installment(settings, installment_number)
    if not field or not lead:
        return None
    return _normalize_enum_value(lead.get(field))


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
    mapped = _parse_mode_enum_map(settings).get(enum_id)
    if mapped:
        return mapped
    # Raw Bitrix value may already be a label ("Cash") instead of an enum ID.
    return enum_id.lower()


def _mode_fields_snapshot(lead: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    """Debug helper: raw values for all installment payment-mode fields."""
    out: dict[str, Any] = {}
    if not lead:
        return out
    for n in (1, 2, 3, 4):
        field = payment_mode_field_for_installment(settings, n)
        if field:
            out[f"{n}:{field}"] = lead.get(field)
    return out


def is_cash_payment_mode(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
) -> bool:
    field = payment_mode_field_for_installment(settings, installment_number)
    raw = lead.get(field) if lead and field else None
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    checked_installment = installment_number

    # If the charge installment mode is blank, fall back to any Cash mode on 1-4.
    if not enum_id and lead:
        for n in (1, 2, 3, 4):
            if n == installment_number:
                continue
            alt = payment_mode_enum_id(lead, installment_number=n, settings=settings)
            if not alt:
                continue
            alt_label = payment_mode_label(lead, installment_number=n, settings=settings)
            if alt in cash_mode_enum_ids(settings) or (alt_label or "").strip().lower() == "cash":
                enum_id = alt
                checked_installment = n
                field = payment_mode_field_for_installment(settings, n)
                raw = lead.get(field) if field else None
                logger.info(
                    "Payment mode fallback | charge_installment=%s used_installment=%s "
                    "field=%s raw=%r",
                    installment_number,
                    n,
                    field or "-",
                    raw,
                )
                break

    if not enum_id:
        logger.info(
            "Payment mode check | installment=%s field=%s raw=%r result=not_cash "
            "reason=missing_or_empty modes=%s",
            installment_number,
            field or "-",
            raw,
            _mode_fields_snapshot(lead, settings),
        )
        return False

    cash_ids = cash_mode_enum_ids(settings)
    label = payment_mode_label(
        lead, installment_number=checked_installment, settings=settings
    )
    by_id = enum_id in cash_ids
    by_label = (label or "").strip().lower() == "cash"
    is_cash = by_id or by_label
    logger.info(
        "Payment mode check | installment=%s checked=%s field=%s raw=%r enum=%s "
        "label=%s cash_ids=%s result=%s",
        installment_number,
        checked_installment,
        field or "-",
        raw,
        enum_id,
        label or "-",
        sorted(cash_ids),
        "cash" if is_cash else "not_cash",
    )
    return is_cash
