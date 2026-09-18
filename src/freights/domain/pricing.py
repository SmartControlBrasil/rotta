from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from .exceptions import InvalidFreightPricing

ZERO = Decimal("0.00")
TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class ChargeLine:
    total_amount: Decimal | None
    is_discount: bool
    charge_type: str


def charge_line_total(*, quantity: Decimal, unit_amount: Decimal) -> Decimal:
    if quantity < 0:
        raise ValueError("Quantidade não pode ser negativa.")
    if unit_amount < 0:
        raise ValueError("Valor unitário não pode ser negativo.")
    return (quantity * unit_amount).quantize(TWOPLACES)


def recalculate_quote_amounts(
    *,
    tax_amount: Decimal | None,
    estimated_cost: Decimal | None,
    charges: list[ChargeLine],
) -> dict[str, Decimal]:
    base_freight = ZERO
    additional_charges = ZERO
    discount_amount = ZERO
    insurance_amount = ZERO
    tax_amount_val = tax_amount or ZERO

    for charge in charges:
        line_total = charge.total_amount or ZERO
        if charge.is_discount or charge.charge_type == "DISCOUNT":
            discount_amount += abs(line_total)
            continue
        if charge.charge_type == "BASE_FREIGHT":
            base_freight += line_total
            continue
        if charge.charge_type == "INSURANCE":
            insurance_amount += line_total
            continue
        additional_charges += line_total

    subtotal = base_freight + additional_charges + insurance_amount
    total_amount = (subtotal - discount_amount + tax_amount_val).quantize(TWOPLACES)
    if total_amount < ZERO:
        raise InvalidFreightPricing("Total da cotação não pode ser negativo.")

    customer_price = total_amount
    gross_margin_amount = None
    gross_margin_percent = None
    if estimated_cost is not None:
        gross_margin_amount = (customer_price - estimated_cost).quantize(TWOPLACES)
        if customer_price > ZERO:
            gross_margin_percent = (
                (gross_margin_amount / customer_price) * Decimal("100")
            ).quantize(TWOPLACES)

    return {
        "base_freight_amount": base_freight.quantize(TWOPLACES),
        "additional_charges": additional_charges.quantize(TWOPLACES),
        "discount_amount": discount_amount.quantize(TWOPLACES),
        "insurance_amount": insurance_amount.quantize(TWOPLACES),
        "total_amount": total_amount,
        "customer_price": customer_price,
        "gross_margin_amount": gross_margin_amount,
        "gross_margin_percent": gross_margin_percent,
    }
