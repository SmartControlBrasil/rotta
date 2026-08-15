from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from src.freights.infrastructure.django.models import FreightQuote, FreightQuoteCharge

ZERO = Decimal("0.00")
TWOPLACES = Decimal("0.01")


def charge_line_total(*, quantity: Decimal, unit_amount: Decimal) -> Decimal:
    if quantity < 0:
        raise ValueError("Quantidade não pode ser negativa.")
    if unit_amount < 0:
        raise ValueError("Valor unitário não pode ser negativo.")
    return (quantity * unit_amount).quantize(TWOPLACES)


def recalculate_quote_amounts(
    quote: FreightQuote,
    charges: list[FreightQuoteCharge] | None = None,
) -> dict[str, Decimal]:
    charge_rows = charges if charges is not None else list(quote.charges.all())

    base_freight = ZERO
    additional_charges = ZERO
    discount_amount = ZERO
    insurance_amount = ZERO
    tax_amount = quote.tax_amount or ZERO

    for charge in charge_rows:
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
    total_amount = (subtotal - discount_amount + tax_amount).quantize(TWOPLACES)
    if total_amount < ZERO:
        raise ValidationError({"total_amount": "Total da cotação não pode ser negativo."})

    customer_price = total_amount
    gross_margin_amount = None
    gross_margin_percent = None
    if quote.estimated_cost is not None:
        gross_margin_amount = (customer_price - quote.estimated_cost).quantize(TWOPLACES)
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
