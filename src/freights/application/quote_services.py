from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.freights.application.pricing_services import (
    recalculate_and_persist_quote_totals,
    sync_quote_charges,
    validate_quote_totals_match_charges,
)
from src.freights.application.services import change_freight_request_status
from src.freights.domain.enums import FreightRequestStatus
from src.freights.domain.pricing import charge_line_total
from src.freights.domain.quote_enums import (
    FreightPricingMethod,
    FreightQuoteChargeType,
    FreightQuoteStatus,
)
from src.freights.domain.quote_state_machine import (
    REQUEST_STATUSES_ALLOWING_QUOTE_CREATION,
    can_transition_quote,
)
from src.freights.domain.state_machine import can_transition
from src.freights.infrastructure.django.models import (
    FreightQuote,
    FreightQuoteReferenceSequence,
    FreightRequest,
)


@dataclass(frozen=True)
class ChargeData:
    charge_type: FreightQuoteChargeType
    description: str = ""
    quantity: Decimal = Decimal("1")
    unit_amount: Decimal = Decimal("0")
    total_amount: Decimal | None = None
    is_discount: bool = False
    sequence: int = 1


@dataclass(frozen=True)
class FreightQuoteData:
    freight_request: FreightRequest
    created_by: Any
    owner: Any | None = None
    pricing_method: FreightPricingMethod = FreightPricingMethod.MANUAL
    currency: str = "BRL"
    valid_until: Any | None = None
    estimated_cost: Decimal | None = None
    estimated_distance_km: Decimal | None = None
    estimated_duration_hours: Decimal | None = None
    tax_amount: Decimal = Decimal("0")
    internal_notes: str = ""
    customer_notes: str = ""
    charges: tuple[ChargeData, ...] = ()


def _allocate_quote_reference_code(*, organization) -> str:
    year = timezone.now().year
    sequence, _created = FreightQuoteReferenceSequence.objects.select_for_update().get_or_create(
        organization=organization,
        year=year,
        defaults={"last_value": 0},
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value"])
    return f"FQ-{year}-{sequence.last_value:06d}"


def _next_quote_version(*, freight_request: FreightRequest) -> int:
    latest = freight_request.quotes.order_by("-version").values_list("version", flat=True).first()
    return (latest or 0) + 1


def build_premises_snapshot(freight_request: FreightRequest) -> dict[str, Any]:
    cargo = getattr(freight_request, "cargo", None)
    pickup = freight_request.pickup_stop
    delivery = freight_request.delivery_stop
    snapshot = {
        "request_id": str(freight_request.id),
        "request_reference": freight_request.reference_code,
        "customer_id": str(freight_request.customer_id),
        "cargo_profile": str(cargo.cargo_profile) if cargo else "",
        "cargo_type": str(cargo.cargo_type) if cargo else "",
        "weight_kg": str(cargo.weight_kg) if cargo and cargo.weight_kg is not None else "",
        "volume_m3": str(cargo.volume_m3) if cargo and cargo.volume_m3 is not None else "",
        "vehicle_type_required": freight_request.vehicle_type_required,
        "body_type_required": freight_request.body_type_required,
        "pickup": {
            "city": pickup.city if pickup else "",
            "state": pickup.state if pickup else "",
        },
        "delivery": {
            "city": delivery.city if delivery else "",
            "state": delivery.state if delivery else "",
        },
    }
    if cargo and cargo.cargo_profile == "REFRIGERATED_CARGO":
        snapshot["temperature_min_c"] = (
            str(cargo.temperature_min_c) if cargo.temperature_min_c is not None else ""
        )
        snapshot["temperature_max_c"] = (
            str(cargo.temperature_max_c) if cargo.temperature_max_c is not None else ""
        )
    return snapshot


def _quote_audit_payload(quote: FreightQuote, *, include_margin: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(quote.id),
        "reference_code": quote.reference_code,
        "version": quote.version,
        "status": str(quote.status),
        "freight_request_id": str(quote.freight_request_id),
        "total_amount": str(quote.total_amount),
        "currency": quote.currency,
        "valid_until": str(quote.valid_until) if quote.valid_until else "",
    }
    if include_margin and quote.estimated_cost is not None:
        payload["estimated_cost"] = str(quote.estimated_cost)
        payload["gross_margin_amount"] = str(quote.gross_margin_amount)
    return payload


def _ensure_request_allows_quote(freight_request: FreightRequest) -> None:
    if freight_request.status not in REQUEST_STATUSES_ALLOWING_QUOTE_CREATION:
        raise ValidationError(
            {"freight_request": ("Solicitação não está em estado adequado para cotação.")}
        )


def _maybe_transition_request_to_quoting(
    freight_request: FreightRequest,
    *,
    actor=None,
) -> None:
    current = FreightRequestStatus(freight_request.status)
    if current in {
        FreightRequestStatus.SUBMITTED,
        FreightRequestStatus.UNDER_REVIEW,
    } and can_transition(current=current, target=FreightRequestStatus.QUOTING):
        change_freight_request_status(
            freight_request,
            status=FreightRequestStatus.QUOTING,
            actor=actor,
        )


def _charge_rows_from_data(charges: tuple[ChargeData, ...]) -> list[dict]:
    rows = []
    for index, charge in enumerate(charges, start=1):
        quantity = charge.quantity
        unit_amount = charge.unit_amount
        total_amount = charge.total_amount
        if total_amount is None:
            total_amount = charge_line_total(quantity=quantity, unit_amount=unit_amount)
        rows.append(
            {
                "charge_type": charge.charge_type.value,
                "description": charge.description,
                "quantity": quantity,
                "unit_amount": unit_amount,
                "total_amount": total_amount,
                "is_discount": charge.is_discount
                or charge.charge_type == FreightQuoteChargeType.DISCOUNT,
                "sequence": charge.sequence or index,
            }
        )
    return rows


def _supersede_quote(quote: FreightQuote, *, actor=None) -> FreightQuote:
    if quote.status == FreightQuoteStatus.SUPERSEDED.value:
        return quote
    before = _quote_audit_payload(quote)
    quote.status = FreightQuoteStatus.SUPERSEDED.value
    quote.full_clean()
    quote.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action="freight_quote_revised",
        actor=actor,
        organization=quote.organization,
        target=quote,
        before=before,
        after=_quote_audit_payload(quote),
        metadata={"superseded": True},
    )
    return quote


def _apply_expiration_if_needed(quote: FreightQuote, *, actor=None) -> FreightQuote:
    if quote.status != FreightQuoteStatus.SENT.value:
        return quote
    if not quote.is_expired:
        return quote
    return _transition_quote(
        quote,
        target=FreightQuoteStatus.EXPIRED,
        actor=actor,
        audit_action="freight_quote_status_changed",
        metadata={"status": FreightQuoteStatus.EXPIRED.value},
    )


def _transition_quote(
    quote: FreightQuote,
    *,
    target: FreightQuoteStatus,
    actor=None,
    audit_action: str,
    metadata: dict | None = None,
    before: dict | None = None,
) -> FreightQuote:
    current = FreightQuoteStatus(quote.status)
    if not can_transition_quote(current=current, target=target):
        raise ValidationError({"status": "Transição de status da cotação não permitida."})
    before_payload = before or _quote_audit_payload(quote)
    quote.status = target.value
    quote.full_clean()
    quote.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action=audit_action,
        actor=actor,
        organization=quote.organization,
        target=quote,
        before=before_payload,
        after=_quote_audit_payload(quote),
        metadata=metadata or {"status": target.value},
    )
    return quote


@transaction.atomic
def create_freight_quote(*, data: FreightQuoteData, actor=None) -> FreightQuote:
    freight_request = data.freight_request
    _ensure_request_allows_quote(freight_request)
    reference_code = _allocate_quote_reference_code(organization=freight_request.organization)
    quote = FreightQuote(
        organization=freight_request.organization,
        freight_request=freight_request,
        created_by=data.created_by,
        owner=data.owner or data.created_by,
        reference_code=reference_code,
        version=_next_quote_version(freight_request=freight_request),
        status=FreightQuoteStatus.DRAFT.value,
        pricing_method=data.pricing_method.value,
        currency=data.currency or "BRL",
        valid_until=data.valid_until,
        estimated_cost=data.estimated_cost,
        estimated_distance_km=data.estimated_distance_km,
        estimated_duration_hours=data.estimated_duration_hours,
        tax_amount=data.tax_amount or Decimal("0"),
        internal_notes=data.internal_notes,
        customer_notes=data.customer_notes,
        premises_snapshot=build_premises_snapshot(freight_request),
    )
    quote.full_clean()
    quote.save()
    if data.charges:
        sync_quote_charges(quote, charge_rows=_charge_rows_from_data(data.charges))
    else:
        recalculate_and_persist_quote_totals(quote)
    _maybe_transition_request_to_quoting(freight_request, actor=actor)
    record_audit_event(
        action="freight_quote_created",
        actor=actor,
        organization=quote.organization,
        target=quote,
        after=_quote_audit_payload(quote),
    )
    return quote


@transaction.atomic
def update_freight_quote_draft(
    quote: FreightQuote,
    *,
    actor=None,
    charges: tuple[ChargeData, ...] | None = None,
    **changes,
) -> FreightQuote:
    if quote.status != FreightQuoteStatus.DRAFT.value:
        raise ValidationError({"status": "Somente cotações em rascunho podem ser editadas."})
    before = _quote_audit_payload(quote)
    allowed_fields = {
        "owner",
        "valid_until",
        "estimated_cost",
        "estimated_distance_km",
        "estimated_duration_hours",
        "tax_amount",
        "internal_notes",
        "customer_notes",
        "pricing_method",
        "currency",
    }
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValidationError({field: "Campo não pode ser atualizado por este caso de uso."})
        if field == "pricing_method" and isinstance(value, FreightPricingMethod):
            value = value.value
        setattr(quote, field, value)
    quote.full_clean()
    quote.save()
    if charges is not None:
        sync_quote_charges(quote, charge_rows=_charge_rows_from_data(charges))
        record_audit_event(
            action="freight_quote_price_recalculated",
            actor=actor,
            organization=quote.organization,
            target=quote,
            before=before,
            after=_quote_audit_payload(quote),
        )
    else:
        recalculate_and_persist_quote_totals(quote)
    record_audit_event(
        action="freight_quote_updated",
        actor=actor,
        organization=quote.organization,
        target=quote,
        before=before,
        after=_quote_audit_payload(quote),
    )
    return quote


@transaction.atomic
def submit_freight_quote_for_review(quote: FreightQuote, *, actor=None) -> FreightQuote:
    validate_quote_totals_match_charges(quote)
    if quote.total_amount <= 0:
        raise ValidationError({"total_amount": "Cotação deve possuir valor total positivo."})
    before = _quote_audit_payload(quote)
    quote.submitted_for_review_at = timezone.now()
    quote.save(update_fields=["submitted_for_review_at", "updated_at"])
    quote = _transition_quote(
        quote,
        target=FreightQuoteStatus.UNDER_REVIEW,
        actor=actor,
        audit_action="freight_quote_submitted_for_review",
        before=before,
    )
    return quote


@transaction.atomic
def approve_freight_quote(quote: FreightQuote, *, actor=None) -> FreightQuote:
    before = _quote_audit_payload(quote)
    quote.approved_by = actor
    quote.approved_at = timezone.now()
    quote.save(update_fields=["approved_by", "approved_at", "updated_at"])
    quote = _transition_quote(
        quote,
        target=FreightQuoteStatus.APPROVED,
        actor=actor,
        audit_action="freight_quote_approved",
        before=before,
    )
    _after_quote_commercial_gate(quote, actor=actor)
    return quote


def _after_quote_commercial_gate(quote: FreightQuote, *, actor=None) -> None:
    from src.freights.application.offer_services import maybe_transition_request_to_ready_to_publish

    maybe_transition_request_to_ready_to_publish(quote.freight_request, actor=actor)


@transaction.atomic
def reject_freight_quote(quote: FreightQuote, *, reason: str, actor=None) -> FreightQuote:
    if not reason.strip():
        raise ValidationError({"rejection_reason": "Motivo de rejeição é obrigatório."})
    before = _quote_audit_payload(quote)
    quote.rejected_by = actor
    quote.rejected_at = timezone.now()
    quote.rejection_reason = reason.strip()
    quote.save(update_fields=["rejected_by", "rejected_at", "rejection_reason", "updated_at"])
    return _transition_quote(
        quote,
        target=FreightQuoteStatus.REJECTED,
        actor=actor,
        audit_action="freight_quote_rejected",
        before=before,
        metadata={"reason": reason.strip()},
    )


@transaction.atomic
def send_freight_quote(quote: FreightQuote, *, actor=None) -> FreightQuote:
    quote = _apply_expiration_if_needed(quote, actor=actor)
    if quote.status == FreightQuoteStatus.EXPIRED.value:
        raise ValidationError({"status": "Cotação vencida não pode ser enviada."})
    if quote.status != FreightQuoteStatus.APPROVED.value:
        raise ValidationError({"status": "Somente cotações aprovadas podem ser enviadas."})
    before = _quote_audit_payload(quote)
    quote.sent_by = actor
    quote.sent_at = timezone.now()
    quote.save(update_fields=["sent_by", "sent_at", "updated_at"])
    quote = _transition_quote(
        quote,
        target=FreightQuoteStatus.SENT,
        actor=actor,
        audit_action="freight_quote_sent",
        before=before,
    )
    _after_quote_commercial_gate(quote, actor=actor)
    return quote


@transaction.atomic
def cancel_freight_quote(quote: FreightQuote, *, reason: str, actor=None) -> FreightQuote:
    if not reason.strip():
        raise ValidationError({"cancellation_reason": "Motivo de cancelamento é obrigatório."})
    before = _quote_audit_payload(quote)
    quote.cancelled_by = actor
    quote.cancelled_at = timezone.now()
    quote.cancellation_reason = reason.strip()
    quote.save(update_fields=["cancelled_by", "cancelled_at", "cancellation_reason", "updated_at"])
    return _transition_quote(
        quote,
        target=FreightQuoteStatus.CANCELLED,
        actor=actor,
        audit_action="freight_quote_cancelled",
        before=before,
        metadata={"reason": reason.strip()},
    )


@transaction.atomic
def revise_freight_quote(
    source_quote: FreightQuote,
    *,
    data: FreightQuoteData,
    actor=None,
) -> FreightQuote:
    if source_quote.status not in {
        FreightQuoteStatus.DRAFT.value,
        FreightQuoteStatus.UNDER_REVIEW.value,
        FreightQuoteStatus.APPROVED.value,
        FreightQuoteStatus.SENT.value,
        FreightQuoteStatus.REJECTED.value,
    }:
        raise ValidationError({"status": "Cotação não pode ser revisada neste estado."})
    if source_quote.status == FreightQuoteStatus.DRAFT.value:
        _supersede_quote(source_quote, actor=actor)
    elif source_quote.status != FreightQuoteStatus.SUPERSEDED.value:
        _supersede_quote(source_quote, actor=actor)
    revision_data = FreightQuoteData(
        freight_request=source_quote.freight_request,
        created_by=data.created_by,
        owner=data.owner or source_quote.owner,
        pricing_method=data.pricing_method,
        currency=data.currency,
        valid_until=data.valid_until,
        estimated_cost=data.estimated_cost,
        estimated_distance_km=data.estimated_distance_km,
        estimated_duration_hours=data.estimated_duration_hours,
        tax_amount=data.tax_amount,
        internal_notes=data.internal_notes,
        customer_notes=data.customer_notes,
        charges=data.charges,
    )
    new_quote = create_freight_quote(data=revision_data, actor=actor)
    new_quote.revision_of = source_quote
    new_quote.premises_snapshot = build_premises_snapshot(source_quote.freight_request)
    new_quote.save(update_fields=["revision_of", "premises_snapshot", "updated_at"])
    record_audit_event(
        action="freight_quote_revised",
        actor=actor,
        organization=new_quote.organization,
        target=new_quote,
        metadata={
            "previous_quote_id": str(source_quote.id),
            "previous_version": source_quote.version,
            "new_version": new_quote.version,
        },
    )
    return new_quote


def get_quote_with_expiration_applied(quote: FreightQuote, *, actor=None) -> FreightQuote:
    return _apply_expiration_if_needed(quote, actor=actor)
