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


@dataclass(frozen=True)
class ProductLine:
    product_id: int
    product_name: str
    quantity: Decimal
    selling_price: Decimal
    tax_rate: Decimal
    tax_included: bool
    catalog_min_price: Decimal | None = None

    @property
    def line_total(self) -> Decimal:
        qty = self.quantity if self.quantity > 0 else Decimal("1")
        base = (self.selling_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if self.tax_included or self.tax_rate <= 0:
            return base
        tax = (base * self.tax_rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return base + tax

    @property
    def is_below_minimum(self) -> bool:
        if self.catalog_min_price is None:
            return True
        return self.selling_price < self.catalog_min_price


@dataclass
class PriceGateResult:
    ok: bool
    lines: list[ProductLine] = field(default_factory=list)
    blocked_lines: list[ProductLine] = field(default_factory=list)
    missing_catalog: list[ProductLine] = field(default_factory=list)
    reason: str = ""
    total_payable: Decimal = Decimal("0.00")
    tax_total: Decimal = Decimal("0.00")

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
                f"selling {line.selling_price:.2f} | catalog min {catalog} | "
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
    return ProductLine(
        product_id=product_id,
        product_name=str(name),
        quantity=_money(row.get("quantity") if "quantity" in row else row.get("QUANTITY") or 1),
        selling_price=_money(row.get("price") if "price" in row else row.get("PRICE")),
        tax_rate=_money(row.get("taxRate") if "taxRate" in row else row.get("TAX_RATE")),
        tax_included=tax_included_raw in ("Y", "1", "TRUE"),
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
    tax_total = Decimal("0.00")

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
        )
        lines.append(line)
        total += line.line_total
        if not line.tax_included and line.tax_rate > 0:
            qty = line.quantity if line.quantity > 0 else Decimal("1")
            base_amount = (line.selling_price * qty).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            tax_total += (base_amount * line.tax_rate / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

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
            f"{line.product_name} selling {line.selling_price:.2f} "
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
        tax_total=tax_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


def product_rows_for_estimate(lines: list[ProductLine]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        rows.append(
            {
                "productId": line.product_id,
                "productName": line.product_name,
                "price": float(line.selling_price),
                "quantity": float(line.quantity if line.quantity > 0 else Decimal("1")),
                "taxRate": float(line.tax_rate) if line.tax_rate > 0 else None,
                "taxIncluded": "Y" if line.tax_included else "N",
                "sort": index * 10,
            }
        )
    return rows
