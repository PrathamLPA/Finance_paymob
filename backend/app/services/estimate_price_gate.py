"""Compare lead product selling prices against the Bitrix catalog minimum."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip()).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (ArithmeticError, ValueError):
        return Decimal("0.00")


def line_money_breakdown(line: "ProductLine") -> tuple[Decimal, Decimal, Decimal]:
    """Return (subtotal_ex_vat, vat, line_payable) for one product line.

    Bitrix ``price`` is always the final unit amount (discounts + taxes already
    applied). Prefer ``unit_gross`` when set so we never add VAT on top of that.
    Legacy rows without ``unit_gross`` keep the old exclusive/inclusive math.
    """
    qty = line.quantity if line.quantity > 0 else Decimal("1")
    if line.unit_gross is not None and line.unit_gross > 0:
        payable = (line.unit_gross * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if line.tax_rate <= 0:
            return payable, Decimal("0.00"), payable
        vat = (payable * line.tax_rate / (Decimal("100") + line.tax_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        subtotal = (payable - vat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return subtotal, vat, payable

    gross = (line.selling_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if line.tax_rate <= 0:
        return gross, Decimal("0.00"), gross
    if line.tax_included:
        vat = (gross * line.tax_rate / (Decimal("100") + line.tax_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        subtotal = (gross - vat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return subtotal, vat, gross
    vat = (gross * line.tax_rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return gross, vat, (gross + vat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ProductLine:
    product_id: int
    product_name: str
    quantity: Decimal
    # Ex-VAT unit price (Bitrix priceExclusive) — for display / VAT breakdown.
    selling_price: Decimal
    tax_rate: Decimal
    tax_included: bool
    catalog_min_price: Decimal | None = None
    # Bitrix `price` — final unit amount including discounts and taxes.
    unit_gross: Decimal | None = None

    @property
    def line_total(self) -> Decimal:
        return line_money_breakdown(self)[2]

    @property
    def compare_unit_price(self) -> Decimal:
        """Unit price compared to catalog min (VAT-inclusive / Bitrix final price)."""
        if self.unit_gross is not None and self.unit_gross > 0:
            return self.unit_gross
        return self.selling_price

    @property
    def is_below_minimum(self) -> bool:
        if self.catalog_min_price is None:
            return True
        # Catalog list prices match Bitrix final/gross amounts (incl. VAT), not ex-VAT.
        return self.compare_unit_price < self.catalog_min_price


@dataclass
class PriceGateResult:
    ok: bool
    lines: list[ProductLine] = field(default_factory=list)
    blocked_lines: list[ProductLine] = field(default_factory=list)
    missing_catalog: list[ProductLine] = field(default_factory=list)
    reason: str = ""
    total_payable: Decimal = Decimal("0.00")
    # VAT added on top of selling price (Bitrix estimate tax_value). Inclusive VAT is excluded.
    tax_total: Decimal = Decimal("0.00")
    # Full VAT for UI (inclusive extracted + exclusive added).
    vat_total: Decimal = Decimal("0.00")
    subtotal: Decimal = Decimal("0.00")

    @property
    def catalog_minimum_total(self) -> Decimal:
        total = Decimal("0.00")
        for line in self.lines:
            if line.catalog_min_price is None:
                continue
            qty = line.quantity if line.quantity > 0 else Decimal("1")
            total += (line.catalog_min_price * qty).quantize(Decimal("0.01"))
        return total

    def summary_comment(self, *, currency: str, amount_paid: Decimal = Decimal("0.00")) -> str:
        remaining = max(self.total_payable - amount_paid, Decimal("0.00"))
        lines = [
            "Estimate / price check",
            f"Total payable: {self.total_payable:.2f} {currency}",
            f"Already paid: {amount_paid:.2f} {currency}",
            f"Amount left: {remaining:.2f} {currency}",
            "",
            "Courses:",
        ]
        for line in self.lines:
            catalog = (
                f"{line.catalog_min_price:.2f}"
                if line.catalog_min_price is not None
                else "missing"
            )
            status = "OK"
            if line.catalog_min_price is None:
                status = "NO CATALOG PRICE"
            elif line.is_below_minimum:
                status = "BELOW MINIMUM"
            lines.append(
                f"- {line.product_name} × {line.quantity:g} | "
                f"selling {line.compare_unit_price:.2f} | catalog min {catalog} | "
                f"tax {line.tax_rate:g}% | {status}"
            )
        if not self.ok and self.reason:
            lines.extend(["", f"Blocked: {self.reason}"])
        return "\n".join(lines)


def parse_product_row(row: dict[str, Any]) -> ProductLine:
    product_id_raw = row.get("productId") if "productId" in row else row.get("PRODUCT_ID")
    try:
        product_id = int(product_id_raw or 0)
    except (TypeError, ValueError):
        product_id = 0

    name = (
        row.get("productName")
        or row.get("PRODUCT_NAME")
        or row.get("name")
        or f"Product {product_id or '?'}"
    )
    tax_included_raw = str(row.get("taxIncluded") or row.get("TAX_INCLUDED") or "N").upper()
    tax_included = tax_included_raw in ("Y", "1", "TRUE")
    tax_rate = _money(row.get("taxRate") if "taxRate" in row else row.get("TAX_RATE"))
    # Bitrix docs: `price` is always the final unit amount (discounts + taxes).
    unit_gross = _money(row.get("price") if "price" in row else row.get("PRICE"))
    if "priceExclusive" in row or "PRICE_EXCLUSIVE" in row:
        price_exclusive = _money(
            row.get("priceExclusive") if "priceExclusive" in row else row.get("PRICE_EXCLUSIVE")
        )
    else:
        price_exclusive = Decimal("0.00")

    if price_exclusive <= 0 and unit_gross > 0 and tax_rate > 0:
        price_exclusive = (
            unit_gross * Decimal("100") / (Decimal("100") + tax_rate)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if price_exclusive <= 0:
        price_exclusive = unit_gross

    return ProductLine(
        product_id=product_id,
        product_name=str(name),
        quantity=_money(row.get("quantity") if "quantity" in row else row.get("QUANTITY") or 1),
        selling_price=price_exclusive,
        tax_rate=tax_rate,
        tax_included=tax_included,
        unit_gross=unit_gross if unit_gross > 0 else None,
    )


def evaluate_price_gate(
    rows: list[dict[str, Any]],
    catalog_prices: dict[int, Decimal],
) -> PriceGateResult:
    if not rows:
        return PriceGateResult(
            ok=False,
            reason=(
                "No products on this lead. Add the course from the Bitrix catalog "
                "before generating a payment link."
            ),
        )

    lines: list[ProductLine] = []
    blocked: list[ProductLine] = []
    missing: list[ProductLine] = []
    total = Decimal("0.00")
    tax_added = Decimal("0.00")
    vat_total = Decimal("0.00")
    subtotal = Decimal("0.00")

    for raw in rows:
        base = parse_product_row(raw)
        catalog_min = catalog_prices.get(base.product_id) if base.product_id else None
        line = ProductLine(
            product_id=base.product_id,
            product_name=base.product_name,
            quantity=base.quantity,
            selling_price=base.selling_price,
            tax_rate=base.tax_rate,
            tax_included=base.tax_included,
            catalog_min_price=catalog_min,
            unit_gross=base.unit_gross,
        )
        lines.append(line)
        line_subtotal, line_vat, line_payable = line_money_breakdown(line)
        total += line_payable
        subtotal += line_subtotal
        vat_total += line_vat
        if not line.tax_included and line.tax_rate > 0:
            tax_added += line_vat

        if line.product_id <= 0:
            missing.append(line)
            blocked.append(line)
        elif catalog_min is None:
            missing.append(line)
            blocked.append(line)
        elif line.is_below_minimum:
            blocked.append(line)

    if missing and all(line.product_id <= 0 for line in missing) and not any(
        line.product_id > 0 for line in lines
    ):
        reason = (
            "Lead product rows are not linked to the catalog. "
            "Pick the course from CRM → Catalog so the minimum price can be checked."
        )
    elif missing:
        names = ", ".join(line.product_name for line in missing)
        reason = f"Catalog minimum price missing for: {names}"
    elif blocked:
        details = "; ".join(
            f"{line.product_name} selling {line.compare_unit_price:.2f} "
            f"< catalog {line.catalog_min_price:.2f}"
            for line in blocked
            if line.catalog_min_price is not None
        )
        reason = (
            "Selling price is below the catalog minimum. "
            f"Raise the price or get approval. ({details})"
        )
    else:
        reason = ""

    return PriceGateResult(
        ok=not blocked,
        lines=lines,
        blocked_lines=blocked,
        missing_catalog=missing,
        reason=reason,
        total_payable=total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        tax_total=tax_added.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        vat_total=vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        subtotal=subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


def product_rows_for_estimate(lines: list[ProductLine]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        qty = line.quantity if line.quantity > 0 else Decimal("1")
        unit_price = line.unit_gross if line.unit_gross and line.unit_gross > 0 else line.selling_price
        rows.append(
            {
                "productId": line.product_id,
                "productName": line.product_name,
                "price": float(unit_price),
                "quantity": float(qty),
                "taxRate": float(line.tax_rate) if line.tax_rate > 0 else None,
                # Bitrix `price` is already final; mark included so Bitrix does not add again.
                "taxIncluded": "Y",
                "sort": index * 10,
            }
        )
    return rows


def serialize_pricing_snapshot(
    lines: list[ProductLine],
    *,
    currency: str,
    total_payable: Decimal | None = None,
) -> dict[str, Any]:
    """Immutable estimate breakdown for the payment page and later finance work."""
    payload_lines: list[dict[str, Any]] = []
    subtotal = Decimal("0.00")
    vat_total = Decimal("0.00")
    payable = Decimal("0.00")
    for line in lines:
        line_subtotal, line_vat, line_payable = line_money_breakdown(line)
        subtotal += line_subtotal
        vat_total += line_vat
        payable += line_payable
        qty = line.quantity if line.quantity > 0 else Decimal("1")
        payload_lines.append(
            {
                "product_id": line.product_id,
                "product_name": line.product_name,
                "quantity": str(qty.quantize(Decimal("0.01"))),
                "unit_price": str(line.selling_price.quantize(Decimal("0.01"))),
                "tax_rate": str(line.tax_rate.quantize(Decimal("0.01"))),
                "tax_included": line.tax_included,
                "subtotal": str(line_subtotal),
                "vat": str(line_vat),
                "line_total": str(line_payable),
                "catalog_min_price": (
                    str(line.catalog_min_price.quantize(Decimal("0.01")))
                    if line.catalog_min_price is not None
                    else None
                ),
            }
        )
    if total_payable is not None:
        payable = total_payable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "currency": currency,
        "subtotal": str(subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "vat_total": str(vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "tax_total": str(vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_payable": str(payable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "lines": payload_lines,
    }


def pricing_snapshot_from_gate(gate: PriceGateResult, *, currency: str) -> dict[str, Any]:
    return serialize_pricing_snapshot(
        gate.lines,
        currency=currency,
        total_payable=gate.total_payable,
    )


def minimal_pricing_snapshot(*, currency: str, total_payable: Decimal) -> dict[str, Any]:
    total = total_payable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "currency": currency,
        "subtotal": str(total),
        "vat_total": "0.00",
        "tax_total": "0.00",
        "total_payable": str(total),
        "lines": [],
    }
