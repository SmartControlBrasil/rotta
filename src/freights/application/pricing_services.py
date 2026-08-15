from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from src.freights.domain.pricing import charge_line_total, recalculate_quote_amounts
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.freights.infrastructure.django.models import FreightQuote, FreightQuoteCharge


@transaction.atomic
def sync_quote_charges(
    quote: FreightQuote,
    *,
    charge_rows: list[dict],
) -> FreightQuote:
    quote.charges.all().delete()
    for index, row in enumerate(charge_rows, start=1):
        quantity = row.get("quantity") or Decimal("1")
        unit_amount = row.get("unit_amount") or Decimal("0")
        total_amount = row.get("total_amount")
        if total_amount is None:
            total_amount = charge_line_total(quantity=quantity, unit_amount=unit_amount)
        charge = FreightQuoteCharge(
            quote=quote,
            charge_type=row.get("charge_type") or FreightQuoteChargeType.OTHER.value,
            description=row.get("description", ""),
            quantity=quantity,
            unit_amount=unit_amount,
            total_amount=total_amount,
            is_discount=row.get("is_discount", False),
            sequence=row.get("sequence") or index,
        )
        charge.full_clean()
        charge.save()
    return recalculate_and_persist_quote_totals(quote)


@transaction.atomic
def recalculate_and_persist_quote_totals(quote: FreightQuote) -> FreightQuote:
    amounts = recalculate_quote_amounts(quote)
    quote.base_freight_amount = amounts["base_freight_amount"]
    quote.additional_charges = amounts["additional_charges"]
    quote.discount_amount = amounts["discount_amount"]
    quote.insurance_amount = amounts["insurance_amount"]
    quote.total_amount = amounts["total_amount"]
    quote.customer_price = amounts["customer_price"]
    quote.full_clean()
    quote.save(
        update_fields=[
            "base_freight_amount",
            "additional_charges",
            "discount_amount",
            "insurance_amount",
            "total_amount",
            "customer_price",
            "updated_at",
        ]
    )
    return quote


def validate_quote_totals_match_charges(quote: FreightQuote) -> None:
    amounts = recalculate_quote_amounts(quote)
    if quote.total_amount != amounts["total_amount"]:
        raise ValidationError(
            {
                "total_amount": (
                    "Total da cotação diverge da composição de itens. Recalcule os valores."
                )
            }
        )
