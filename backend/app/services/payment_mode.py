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
    raw = (getattr(settings, "cash_mode_enum_ids", None) or "5774,5786").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def bank_transfer_mode_enum_ids(settings: Settings) -> set[str]:
    raw = (getattr(settings, "bank_transfer_mode_enum_ids", None) or "5790").strip()
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
    bitrix_enum_labels: dict[str, str] | None = None,
) -> str | None:
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    if not enum_id:
        return None
    if bitrix_enum_labels and enum_id in bitrix_enum_labels:
        return bitrix_enum_labels[enum_id].strip().lower()
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


def _label_means_cash(label: str | None) -> bool:
    if not label:
        return False
    normalized = label.strip().lower().replace("_", " ").replace("-", " ")
    return normalized == "cash" or normalized.startswith("cash ")


def _label_means_bank_transfer(label: str | None) -> bool:
    if not label:
        return False
    normalized = label.strip().lower().replace("_", " ").replace("-", " ")
    return (
        normalized in ("bank transfer", "banktransfer", "wire transfer", "wire")
        or normalized.startswith("bank transfer")
        or normalized.startswith("banktransfer")
    )


def is_cash_payment_mode(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
    bitrix_enum_labels: dict[str, str] | None = None,
) -> bool:
    field = payment_mode_field_for_installment(settings, installment_number)
    raw = lead.get(field) if lead and field else None
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    checked_installment = installment_number
    cash_ids = cash_mode_enum_ids(settings)
    configured_map = _parse_mode_enum_map(settings)

    # If the charge installment mode is blank, fall back to any Cash mode on 1-4.
    if not enum_id and lead:
        for n in (1, 2, 3, 4):
            if n == installment_number:
                continue
            alt = payment_mode_enum_id(lead, installment_number=n, settings=settings)
            if not alt:
                continue
            alt_label = payment_mode_label(
                lead,
                installment_number=n,
                settings=settings,
                bitrix_enum_labels=bitrix_enum_labels,
            )
            if alt in cash_ids or _label_means_cash(alt_label):
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
            "reason=missing_or_empty modes=%s cash_ids=%s",
            installment_number,
            field or "-",
            raw,
            _mode_fields_snapshot(lead, settings),
            sorted(cash_ids),
        )
        return False

    label = payment_mode_label(
        lead,
        installment_number=checked_installment,
        settings=settings,
        bitrix_enum_labels=bitrix_enum_labels,
    )
    by_id = enum_id in cash_ids
    by_label = _label_means_cash(label)
    is_cash = by_id or by_label

    unknown_in_config = enum_id not in configured_map and enum_id not in (
        bitrix_enum_labels or {}
    )
    if not is_cash and unknown_in_config:
        logger.warning(
            "Payment mode UNKNOWN enum | installment=%s field=%s raw=%r enum=%s "
            "cash_ids=%s configured_map_ids=%s bitrix_labels=%s modes=%s | "
            "Update CASH_MODE_ENUM_IDS / BITRIX_PAYMENT_MODE_ENUM_MAP to match Bitrix "
            "(open the Payment 1 Mode list in Bitrix and copy the Cash option ID).",
            installment_number,
            field or "-",
            raw,
            enum_id,
            sorted(cash_ids),
            sorted(configured_map.keys()),
            bitrix_enum_labels or {},
            _mode_fields_snapshot(lead, settings),
        )
    else:
        logger.info(
            "Payment mode check | installment=%s checked=%s field=%s raw=%r enum=%s "
            "label=%s cash_ids=%s by_id=%s by_label=%s result=%s",
            installment_number,
            checked_installment,
            field or "-",
            raw,
            enum_id,
            label or "-",
            sorted(cash_ids),
            by_id,
            by_label,
            "cash" if is_cash else "not_cash",
        )
    return is_cash


def is_bank_transfer_payment_mode(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
    bitrix_enum_labels: dict[str, str] | None = None,
) -> bool:
    """True when mode is bank transfer. Cash takes precedence if both would match."""
    if is_cash_payment_mode(
        lead,
        installment_number=installment_number,
        settings=settings,
        bitrix_enum_labels=bitrix_enum_labels,
    ):
        return False

    field = payment_mode_field_for_installment(settings, installment_number)
    raw = lead.get(field) if lead and field else None
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    checked_installment = installment_number
    bt_ids = bank_transfer_mode_enum_ids(settings)

    if not enum_id and lead:
        for n in (1, 2, 3, 4):
            if n == installment_number:
                continue
            alt = payment_mode_enum_id(lead, installment_number=n, settings=settings)
            if not alt:
                continue
            alt_label = payment_mode_label(
                lead,
                installment_number=n,
                settings=settings,
                bitrix_enum_labels=bitrix_enum_labels,
            )
            if alt in bt_ids or _label_means_bank_transfer(alt_label):
                enum_id = alt
                checked_installment = n
                field = payment_mode_field_for_installment(settings, n)
                raw = lead.get(field) if field else None
                logger.info(
                    "Payment mode bank_transfer fallback | charge_installment=%s "
                    "used_installment=%s field=%s raw=%r",
                    installment_number,
                    n,
                    field or "-",
                    raw,
                )
                break

    if not enum_id:
        return False

    label = payment_mode_label(
        lead,
        installment_number=checked_installment,
        settings=settings,
        bitrix_enum_labels=bitrix_enum_labels,
    )
    by_id = enum_id in bt_ids
    by_label = _label_means_bank_transfer(label)
    is_bt = by_id or by_label
    logger.info(
        "Payment mode bank_transfer check | installment=%s checked=%s field=%s "
        "raw=%r enum=%s label=%s bt_ids=%s by_id=%s by_label=%s result=%s",
        installment_number,
        checked_installment,
        field or "-",
        raw,
        enum_id,
        label or "-",
        sorted(bt_ids),
        by_id,
        by_label,
        "bank_transfer" if is_bt else "not_bank_transfer",
    )
    return is_bt


async def _load_payment_mode_bitrix_labels(
    *,
    installment_number: int,
    settings: Settings,
    bitrix: Any,
) -> dict[str, str]:
    field = payment_mode_field_for_installment(settings, installment_number)
    bitrix_labels: dict[str, str] = {}
    if field and hasattr(bitrix, "get_lead_userfield_enum_map"):
        try:
            bitrix_labels = await bitrix.get_lead_userfield_enum_map(field)
            if bitrix_labels:
                logger.info(
                    "Payment mode Bitrix enums | field=%s options=%s",
                    field,
                    {k: v for k, v in sorted(bitrix_labels.items())},
                )
        except Exception:
            logger.exception(
                "Could not load Bitrix enum labels for payment-mode field %s", field
            )
    return bitrix_labels


def _label_means_tabby(label: str | None) -> bool:
    if not label:
        return False
    normalized = label.strip().lower().replace("_", " ").replace("-", " ")
    return normalized == "tabby" or normalized.startswith("tabby ")


def _label_means_tamara(label: str | None) -> bool:
    if not label:
        return False
    normalized = label.strip().lower().replace("_", " ").replace("-", " ")
    return normalized == "tamara" or normalized.startswith("tamara ")


def _label_means_website_payment(label: str | None) -> bool:
    if not label:
        return False
    normalized = label.strip().lower().replace("_", " ").replace("-", " ")
    return normalized in (
        "website payment",
        "website",
        "online",
        "card",
        "cards",
    ) or "website payment" in normalized


def _card_integration_id(settings: Settings) -> int:
    card = int(getattr(settings, "paymob_integration_id_card", 0) or 0)
    if card > 0:
        return card
    return int(getattr(settings, "paymob_integration_id", 0) or 0)


def resolve_paymob_payment_method_ids(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
    bitrix_enum_labels: dict[str, str] | None = None,
) -> list[int]:
    """Map Bitrix payment mode → Paymob Intention payment_methods list.

    - Tabby → Tabby integration only
    - Tamara → Tamara integration only
    - Website payment → Card + Tabby + Tamara (customer chooses on Paymob)
    - Card / online / empty / unknown → Card only
    """
    card_id = _card_integration_id(settings)
    tabby_id = int(getattr(settings, "paymob_integration_id_tabby", 0) or 0)
    tamara_id = int(getattr(settings, "paymob_integration_id_tamara", 0) or 0)

    label = payment_mode_label(
        lead,
        installment_number=installment_number,
        settings=settings,
        bitrix_enum_labels=bitrix_enum_labels,
    )
    enum_id = payment_mode_enum_id(
        lead, installment_number=installment_number, settings=settings
    )
    configured_map = _parse_mode_enum_map(settings)
    mapped = (configured_map.get(enum_id) or "").strip().lower() if enum_id else ""
    effective = (label or mapped or "").strip().lower()

    methods: list[int] = []
    if _label_means_tabby(effective) or mapped == "tabby":
        if tabby_id > 0:
            methods = [tabby_id]
    elif _label_means_tamara(effective) or mapped == "tamara":
        if tamara_id > 0:
            methods = [tamara_id]
    elif _label_means_website_payment(effective) or mapped in (
        "website_payment",
        "website payment",
        "online",
    ):
        # Website payment: offer all enabled BNPL + card on unified checkout.
        for mid in (card_id, tabby_id, tamara_id):
            if mid > 0 and mid not in methods:
                methods.append(mid)
    else:
        if card_id > 0:
            methods = [card_id]

    if not methods and card_id > 0:
        methods = [card_id]

    logger.info(
        "Paymob payment methods | installment=%s enum=%s label=%s mapped=%s methods=%s",
        installment_number,
        enum_id or "-",
        label or "-",
        mapped or "-",
        methods,
    )
    return methods


async def resolve_paymob_payment_method_ids_async(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
    bitrix: Any,
) -> list[int]:
    bitrix_labels = await _load_payment_mode_bitrix_labels(
        installment_number=installment_number,
        settings=settings,
        bitrix=bitrix,
    )
    return resolve_paymob_payment_method_ids(
        lead,
        installment_number=installment_number,
        settings=settings,
        bitrix_enum_labels=bitrix_labels or None,
    )


async def resolve_is_cash_payment_mode(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
    bitrix: Any,
) -> bool:
    """Cash check with live Bitrix enumeration labels for the payment-mode field."""
    bitrix_labels = await _load_payment_mode_bitrix_labels(
        installment_number=installment_number,
        settings=settings,
        bitrix=bitrix,
    )
    return is_cash_payment_mode(
        lead,
        installment_number=installment_number,
        settings=settings,
        bitrix_enum_labels=bitrix_labels or None,
    )


async def resolve_is_bank_transfer_payment_mode(
    lead: dict[str, Any] | None,
    *,
    installment_number: int,
    settings: Settings,
    bitrix: Any,
) -> bool:
    """Bank transfer check with live Bitrix enumeration labels."""
    bitrix_labels = await _load_payment_mode_bitrix_labels(
        installment_number=installment_number,
        settings=settings,
        bitrix=bitrix,
    )
    return is_bank_transfer_payment_mode(
        lead,
        installment_number=installment_number,
        settings=settings,
        bitrix_enum_labels=bitrix_labels or None,
    )
