"""Lead course seats for the payment registration form."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.integrations.base import BitrixIntegration
from app.services.estimate_price_gate import parse_product_row


def courses_from_product_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse lead product rows into course seats the customer can assign."""
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, int] = {}
    synthetic = -1

    for raw in rows:
        line = parse_product_row(raw)
        if line.product_id > 0:
            product_id = line.product_id
        else:
            name_key = line.product_name.strip().lower()
            if name_key in by_name:
                product_id = by_name[name_key]
            else:
                product_id = synthetic
                by_name[name_key] = product_id
                synthetic -= 1

        qty = int(line.quantity) if line.quantity == line.quantity.to_integral_value() else int(line.quantity)
        if qty < 1:
            qty = 1

        existing = by_id.get(product_id)
        if existing:
            existing["quantity"] = int(existing["quantity"]) + qty
            continue

        by_id[product_id] = {
            "product_id": product_id,
            "product_name": line.product_name,
            "quantity": qty,
        }

    return sorted(by_id.values(), key=lambda c: str(c["product_name"]).lower())


async def load_lead_courses(bitrix: BitrixIntegration, lead_id: int | None) -> list[dict[str, Any]]:
    if not lead_id:
        return []
    rows = await bitrix.list_product_rows(owner_type="L", owner_id=int(lead_id))
    return courses_from_product_rows(rows)


def total_seats(courses: list[dict[str, Any]]) -> int:
    return sum(int(c.get("quantity") or 0) for c in courses)


def participants_for_buyer(
    courses: list[dict[str, Any]],
    *,
    name: str,
    email: str,
) -> list[dict[str, Any]]:
    """Buyer attends every seat — used when the purchase is "for me"."""
    people: list[dict[str, Any]] = []
    for course in courses:
        for _ in range(int(course.get("quantity") or 0)):
            people.append(
                {
                    "name": name,
                    "email": email,
                    "product_id": int(course["product_id"]),
                    "product_name": str(course["product_name"]),
                }
            )
    return people


def validate_participants(
    courses: list[dict[str, Any]],
    participants: list[dict[str, Any]] | None,
) -> str | None:
    """Ensure every purchased seat is assigned to exactly one candidate."""
    seats = total_seats(courses)
    if seats == 0:
        return None

    items = participants or []
    if len(items) != seats:
        return (
            f"Please assign all {seats} course seat(s). "
            f"You provided {len(items)}."
        )

    allowed = {int(c["product_id"]): int(c["quantity"]) for c in courses}
    names = {int(c["product_id"]): str(c["product_name"]) for c in courses}
    assigned: Counter[int] = Counter()

    for index, person in enumerate(items, start=1):
        name = str(person.get("name") or "").strip()
        email = str(person.get("email") or "").strip()
        try:
            product_id = int(person.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0

        if not name:
            return f"Please enter the name for candidate {index}."
        if not email:
            return f"Please enter the email for candidate {index}."
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return f"Please enter a valid email for candidate {index}."
        if product_id not in allowed:
            return f"Course assignment missing for candidate {index}."
        assigned[product_id] += 1

    for product_id, quantity in allowed.items():
        got = assigned.get(product_id, 0)
        if got != quantity:
            label = names.get(product_id, f"course {product_id}")
            return (
                f'"{label}" has {quantity} seat(s) on this order, '
                f"but {got} candidate(s) were assigned."
            )

    return None


def normalize_participants(
    participants: list[dict[str, Any]] | None,
    courses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = {int(c["product_id"]): str(c["product_name"]) for c in courses}
    cleaned: list[dict[str, Any]] = []
    for person in participants or []:
        try:
            product_id = int(person.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        cleaned.append(
            {
                "name": str(person.get("name") or "").strip(),
                "email": str(person.get("email") or "").strip(),
                "product_id": product_id,
                "product_name": names.get(product_id)
                or str(person.get("product_name") or "").strip(),
            }
        )
    return cleaned
