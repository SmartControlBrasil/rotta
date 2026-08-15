from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.quote_services import build_premises_snapshot
from src.freights.domain.enums import FreightCargoProfile, FreightRequestStatus
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.domain.offer_state_machine import (
    QUOTE_STATUSES_ELIGIBLE_FOR_OFFER,
    can_transition_offer,
)
from src.freights.domain.state_machine import can_transition
from src.freights.infrastructure.django.models import (
    FreightOffer,
    FreightOfferReferenceSequence,
    FreightOfferTarget,
    FreightQuote,
    FreightRequest,
)


@dataclass(frozen=True)
class FreightOfferData:
    freight_request: FreightRequest
    freight_quote: FreightQuote
    created_by: Any
    offer_amount: Decimal
    audience: FreightOfferAudience = FreightOfferAudience.CARRIERS
    expires_at: Any | None = None
    owner: Any | None = None
    internal_notes: str = ""
    currency: str = "BRL"


def build_offer_premises_snapshot(freight_request: FreightRequest) -> dict[str, Any]:
    snapshot = build_premises_snapshot(freight_request)
    cargo = getattr(freight_request, "cargo", None)
    if cargo and cargo.cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
        if cargo.target_temperature_c is not None:
            snapshot["target_temperature_c"] = str(cargo.target_temperature_c)
    return snapshot


def _allocate_offer_reference_code(*, organization) -> str:
    year = timezone.now().year
    sequence, _created = FreightOfferReferenceSequence.objects.select_for_update().get_or_create(
        organization=organization,
        year=year,
        defaults={"last_value": 0},
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value"])
    return f"FO-{year}-{sequence.last_value:06d}"


def _offer_audit_payload(offer: FreightOffer, *, include_margin: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(offer.id),
        "reference_code": offer.reference_code,
        "status": str(offer.status),
        "freight_request_id": str(offer.freight_request_id),
        "freight_quote_id": str(offer.freight_quote_id),
        "offer_amount": str(offer.offer_amount),
        "currency": offer.currency,
        "audience": str(offer.audience),
        "expires_at": offer.expires_at.isoformat() if offer.expires_at else "",
    }
    if include_margin and offer.freight_quote_id:
        payload["customer_price"] = str(offer.freight_quote.customer_price)
        spread = offer.spread_amount
        if spread is not None:
            payload["spread_amount"] = str(spread)
    return payload


def _validate_quote_for_offer(
    *,
    freight_request: FreightRequest,
    freight_quote: FreightQuote,
) -> None:
    if freight_quote.freight_request_id != freight_request.id:
        raise ValidationError({"freight_quote": "Cotação não pertence à solicitação informada."})
    if freight_quote.organization_id != freight_request.organization_id:
        raise ValidationError({"freight_quote": "Cotação fora do escopo organizacional."})
    if freight_quote.status not in QUOTE_STATUSES_ELIGIBLE_FOR_OFFER:
        raise ValidationError(
            {"freight_quote": "Cotação deve estar aprovada ou enviada para gerar oferta."}
        )


def _ensure_request_allows_offer_creation(freight_request: FreightRequest) -> None:
    blocked = {
        FreightRequestStatus.DRAFT.value,
        FreightRequestStatus.CANCELLED.value,
        FreightRequestStatus.CLOSED.value,
    }
    if freight_request.status in blocked:
        raise ValidationError(
            {"freight_request": "Solicitação não está em estado adequado para oferta."}
        )
    if freight_request.status != FreightRequestStatus.READY_TO_PUBLISH.value:
        raise ValidationError(
            {
                "freight_request": (
                    "Solicitação deve estar em READY_TO_PUBLISH. "
                    "Gate comercial: cotação aprovada ou enviada."
                )
            }
        )


def maybe_transition_request_to_ready_to_publish(
    freight_request: FreightRequest,
    *,
    actor=None,
) -> None:
    """Gate comercial: QUOTING → READY_TO_PUBLISH com quote APPROVED ou SENT."""
    from src.freights.application.services import change_freight_request_status

    current = FreightRequestStatus(freight_request.status)
    if current != FreightRequestStatus.QUOTING:
        return
    has_eligible_quote = freight_request.quotes.filter(
        status__in=QUOTE_STATUSES_ELIGIBLE_FOR_OFFER
    ).exists()
    if not has_eligible_quote:
        return
    if can_transition(current=current, target=FreightRequestStatus.READY_TO_PUBLISH):
        change_freight_request_status(
            freight_request,
            status=FreightRequestStatus.READY_TO_PUBLISH,
            actor=actor,
        )


def _transition_offer(
    offer: FreightOffer,
    *,
    target: FreightOfferStatus,
    actor=None,
    audit_action: str,
    before: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> FreightOffer:
    current = FreightOfferStatus(offer.status)
    if not can_transition_offer(current=current, target=target):
        raise ValidationError({"status": f"Transição inválida: {current.value} → {target.value}."})
    offer.status = target.value
    offer.save(update_fields=["status", "updated_at"])
    after = _offer_audit_payload(offer)
    record_audit_event(
        action=audit_action,
        actor=actor,
        organization=offer.organization,
        target=offer,
        metadata={
            "before": before,
            "after": after,
            **(metadata or {}),
        },
    )
    return offer


def _validate_offer_amount(offer_amount: Decimal) -> None:
    if offer_amount < 0:
        raise ValidationError({"offer_amount": "Valor da oferta não pode ser negativo."})


def _validate_private_targets(offer: FreightOffer) -> None:
    if offer.audience != FreightOfferAudience.PRIVATE.value:
        return
    if not offer.targets.exists():
        raise ValidationError({"targets": "Oferta privada exige ao menos um target."})


@transaction.atomic
def create_freight_offer(*, data: FreightOfferData, actor=None) -> FreightOffer:
    _ensure_request_allows_offer_creation(data.freight_request)
    _validate_quote_for_offer(
        freight_request=data.freight_request,
        freight_quote=data.freight_quote,
    )
    _validate_offer_amount(data.offer_amount)
    reference_code = _allocate_offer_reference_code(organization=data.freight_request.organization)
    offer = FreightOffer.objects.create(
        organization=data.freight_request.organization,
        freight_request=data.freight_request,
        freight_quote=data.freight_quote,
        created_by=data.created_by,
        owner=data.owner or data.created_by,
        reference_code=reference_code,
        status=FreightOfferStatus.DRAFT.value,
        offer_amount=data.offer_amount,
        currency=data.currency,
        audience=data.audience.value,
        expires_at=data.expires_at,
        premises_snapshot=build_offer_premises_snapshot(data.freight_request),
        internal_notes=data.internal_notes.strip(),
    )
    record_audit_event(
        action="freight_offer_created",
        actor=actor,
        organization=offer.organization,
        target=offer,
        metadata={"after": _offer_audit_payload(offer)},
    )
    return offer


@transaction.atomic
def update_freight_offer_draft(
    offer: FreightOffer,
    *,
    actor=None,
    offer_amount: Decimal | None = None,
    audience: FreightOfferAudience | None = None,
    expires_at=None,
    internal_notes: str | None = None,
    owner=None,
) -> FreightOffer:
    if offer.status != FreightOfferStatus.DRAFT.value:
        raise ValidationError({"status": "Somente rascunhos podem ser editados."})
    before = _offer_audit_payload(offer)
    update_fields = ["updated_at"]
    if offer_amount is not None:
        _validate_offer_amount(offer_amount)
        offer.offer_amount = offer_amount
        update_fields.append("offer_amount")
    if audience is not None:
        offer.audience = audience.value
        update_fields.append("audience")
    if expires_at is not None:
        offer.expires_at = expires_at
        update_fields.append("expires_at")
    if internal_notes is not None:
        offer.internal_notes = internal_notes.strip()
        update_fields.append("internal_notes")
    if owner is not None:
        offer.owner = owner
        update_fields.append("owner")
    offer.save(update_fields=update_fields)
    after = _offer_audit_payload(offer)
    record_audit_event(
        action="freight_offer_updated",
        actor=actor,
        organization=offer.organization,
        target=offer,
        metadata={"before": before, "after": after},
    )
    return offer


@transaction.atomic
def mark_freight_offer_ready(offer: FreightOffer, *, actor=None) -> FreightOffer:
    if offer.offer_amount <= 0:
        raise ValidationError(
            {"offer_amount": "Valor da oferta deve ser positivo para marcar pronta."}
        )
    before = _offer_audit_payload(offer)
    offer.ready_at = timezone.now()
    offer.save(update_fields=["ready_at", "updated_at"])
    offer = _transition_offer(
        offer,
        target=FreightOfferStatus.READY,
        actor=actor,
        audit_action="freight_offer_ready",
        before=before,
    )
    return offer


def _refresh_snapshot_on_publish(offer: FreightOffer) -> None:
    offer.premises_snapshot = build_offer_premises_snapshot(offer.freight_request)
    offer.save(update_fields=["premises_snapshot", "updated_at"])


@transaction.atomic
def publish_freight_offer(offer: FreightOffer, *, actor=None) -> FreightOffer:
    if offer.status != FreightOfferStatus.READY.value:
        raise ValidationError({"status": "Somente ofertas prontas podem ser publicadas."})
    offer = apply_offer_expiration_if_needed(offer, actor=actor)
    if offer.status == FreightOfferStatus.EXPIRED.value:
        raise ValidationError({"status": "Oferta expirada não pode ser publicada."})
    if offer.offer_amount <= 0:
        raise ValidationError({"offer_amount": "Valor da oferta deve ser positivo."})
    if not offer.expires_at:
        raise ValidationError({"expires_at": "Validade é obrigatória para publicação."})
    if offer.expires_at <= timezone.now():
        raise ValidationError({"expires_at": "Validade deve ser futura."})
    _ensure_request_allows_offer_creation(offer.freight_request)
    _validate_private_targets(offer)
    before = _offer_audit_payload(offer)
    _refresh_snapshot_on_publish(offer)
    offer.published_at = timezone.now()
    offer.paused_at = None
    offer.save(update_fields=["published_at", "paused_at", "updated_at"])
    return _transition_offer(
        offer,
        target=FreightOfferStatus.PUBLISHED,
        actor=actor,
        audit_action="freight_offer_published",
        before=before,
    )


@transaction.atomic
def pause_freight_offer(offer: FreightOffer, *, actor=None) -> FreightOffer:
    before = _offer_audit_payload(offer)
    offer.paused_at = timezone.now()
    offer.save(update_fields=["paused_at", "updated_at"])
    return _transition_offer(
        offer,
        target=FreightOfferStatus.PAUSED,
        actor=actor,
        audit_action="freight_offer_paused",
        before=before,
    )


@transaction.atomic
def resume_freight_offer(offer: FreightOffer, *, actor=None) -> FreightOffer:
    offer = apply_offer_expiration_if_needed(offer, actor=actor)
    if offer.status == FreightOfferStatus.EXPIRED.value:
        raise ValidationError({"status": "Oferta expirada não pode ser retomada."})
    if not offer.expires_at or offer.expires_at <= timezone.now():
        raise ValidationError({"expires_at": "Oferta fora da validade não pode ser retomada."})
    before = _offer_audit_payload(offer)
    offer.paused_at = None
    offer.save(update_fields=["paused_at", "updated_at"])
    return _transition_offer(
        offer,
        target=FreightOfferStatus.PUBLISHED,
        actor=actor,
        audit_action="freight_offer_resumed",
        before=before,
    )


@transaction.atomic
def cancel_freight_offer(offer: FreightOffer, *, reason: str, actor=None) -> FreightOffer:
    if not reason.strip():
        raise ValidationError({"cancellation_reason": "Motivo de cancelamento é obrigatório."})
    if offer.status in {
        FreightOfferStatus.CANCELLED.value,
        FreightOfferStatus.EXPIRED.value,
        FreightOfferStatus.CLOSED.value,
    }:
        raise ValidationError({"status": "Oferta não pode ser cancelada neste estado."})
    before = _offer_audit_payload(offer)
    offer.cancelled_by = actor
    offer.cancelled_at = timezone.now()
    offer.cancellation_reason = reason.strip()
    offer.save(update_fields=["cancelled_by", "cancelled_at", "cancellation_reason", "updated_at"])
    return _transition_offer(
        offer,
        target=FreightOfferStatus.CANCELLED,
        actor=actor,
        audit_action="freight_offer_cancelled",
        before=before,
        metadata={"reason": reason.strip()},
    )


@transaction.atomic
def apply_offer_expiration_if_needed(offer: FreightOffer, *, actor=None) -> FreightOffer:
    if offer.status not in {
        FreightOfferStatus.PUBLISHED.value,
        FreightOfferStatus.PAUSED.value,
    }:
        return offer
    if not offer.is_expired:
        return offer
    before = _offer_audit_payload(offer)
    return _transition_offer(
        offer,
        target=FreightOfferStatus.EXPIRED,
        actor=actor,
        audit_action="freight_offer_expired",
        before=before,
    )


@transaction.atomic
def add_freight_offer_target(
    offer: FreightOffer,
    *,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
    actor=None,
) -> FreightOfferTarget:
    if offer.audience != FreightOfferAudience.PRIVATE.value:
        raise ValidationError({"audience": "Targets só se aplicam a ofertas privadas."})
    if (carrier is None) == (driver is None):
        raise ValidationError({"target": "Informe transportadora ou motorista, não ambos."})
    if carrier and carrier.tenant_id != offer.organization_id:
        raise ValidationError({"carrier": "Transportadora fora do tenant da oferta."})
    if driver and driver.organization_id != offer.organization_id:
        raise ValidationError({"driver": "Motorista fora do tenant da oferta."})
    target, created = FreightOfferTarget.objects.get_or_create(
        offer=offer,
        carrier=carrier,
        driver=driver,
    )
    if created:
        record_audit_event(
            action="freight_offer_target_added",
            actor=actor,
            organization=offer.organization,
            target=offer,
            metadata={
                "target_id": str(target.id),
                "carrier_id": str(carrier.id) if carrier else "",
                "driver_id": str(driver.id) if driver else "",
            },
        )
    return target


@transaction.atomic
def remove_freight_offer_target(
    target: FreightOfferTarget,
    *,
    actor=None,
) -> None:
    offer = target.offer
    metadata = {
        "target_id": str(target.id),
        "carrier_id": str(target.carrier_id) if target.carrier_id else "",
        "driver_id": str(target.driver_id) if target.driver_id else "",
    }
    target.delete()
    record_audit_event(
        action="freight_offer_target_removed",
        actor=actor,
        organization=offer.organization,
        target=offer,
        metadata=metadata,
    )


def get_offer_with_expiration_applied(offer: FreightOffer, *, actor=None) -> FreightOffer:
    return apply_offer_expiration_if_needed(offer, actor=actor)
