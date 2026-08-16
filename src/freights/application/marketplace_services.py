from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.matching.eligibility import (
    MatchEligibilityStatus,
    evaluate_carrier_eligibility,
    evaluate_driver_eligibility,
    evaluate_private_target_access,
    evaluate_vehicle_eligibility,
    load_private_target_ids,
    merge_eligibility_results,
    validate_candidate_shape,
)
from src.freights.application.matching.events import record_marketplace_event
from src.freights.domain.matching_enums import (
    FreightOfferInterestStatus,
    FreightOfferSelectionStatus,
    MarketplaceEventType,
    SelectionDeclineReason,
)
from src.freights.domain.offer_enums import FreightOfferStatus
from src.freights.infrastructure.django.models import (
    FreightOffer,
    FreightOfferInterest,
    FreightOfferInvitation,
    FreightOfferSelection,
)
from src.vehicles.infrastructure.django.models import Vehicle


def check_candidate_eligibility(
    *,
    offer: FreightOffer,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
    vehicle: Vehicle | None = None,
) -> bool:
    shape = validate_candidate_shape(carrier=carrier, driver=driver, vehicle=vehicle)
    if shape.status == MatchEligibilityStatus.INELIGIBLE:
        return False
    results = [shape]

    target_carrier_ids, target_driver_ids = load_private_target_ids(offer)
    results.append(
        evaluate_private_target_access(
            offer=offer,
            carrier=carrier,
            driver=driver,
            target_carrier_ids=target_carrier_ids,
            target_driver_ids=target_driver_ids,
        )
    )

    if carrier:
        results.append(evaluate_carrier_eligibility(offer=offer, carrier=carrier))
    if driver:
        results.append(evaluate_driver_eligibility(offer=offer, driver=driver))
    if vehicle:
        refrigeration = getattr(vehicle, "refrigeration_profile", None)
        results.append(
            evaluate_vehicle_eligibility(
                offer=offer,
                vehicle=vehicle,
                refrigeration=refrigeration,
            )
        )

    merged = merge_eligibility_results(*results)
    return merged.status != MatchEligibilityStatus.INELIGIBLE


def _build_candidate_snapshots(
    *,
    offer: FreightOffer,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
    vehicle: Vehicle | None = None,
    interest: FreightOfferInterest | None = None,
) -> dict[str, Any]:
    snapshots = {}

    if carrier:
        snapshots["carrier_snapshot"] = {
            "id": str(carrier.id),
            "trade_name": carrier.trade_name,
            "organization_name": carrier.organization.name,
            "document_number": carrier.organization.document,
            "email": carrier.email,
        }
    if driver:
        snapshots["driver_snapshot"] = {
            "id": str(driver.id),
            "full_name": driver.full_name,
            "status": driver.status,
            "availability_status": driver.availability_status,
        }
    if vehicle:
        snapshots["vehicle_snapshot"] = {
            "id": str(vehicle.id),
            "plate": vehicle.plate,
            "vehicle_type": vehicle.vehicle_type,
            "cargo_profile": vehicle.cargo_profile,
            "capacity_weight_kg": (
                str(vehicle.capacity_weight_kg) if vehicle.capacity_weight_kg else None
            ),
        }

    snapshot = offer.premises_snapshot or {}
    snapshots["route_snapshot"] = {
        "pickup": snapshot.get("pickup", {}),
        "delivery": snapshot.get("delivery", {}),
    }
    snapshots["cargo_snapshot"] = {
        "cargo_profile": snapshot.get("cargo_profile", ""),
        "weight_kg": snapshot.get("weight_kg", None),
        "temperature_min_c": snapshot.get("temperature_min_c", None),
        "temperature_max_c": snapshot.get("temperature_max_c", None),
    }
    snapshots["premises_snapshot"] = snapshot

    if interest and interest.match_candidate:
        cand = interest.match_candidate
        snapshots["match_score_snapshot"] = cand.total_score
        snapshots["rank_snapshot"] = cand.rank_position
        snapshots["algorithm_version_snapshot"] = cand.algorithm_version
        route_intent_bonus = cand.score_explanation.get("route_intent", {}).get("bonus", 0.0)
        snapshots["route_intent_bonus_snapshot"] = Decimal(str(route_intent_bonus))
    else:
        snapshots["match_score_snapshot"] = None
        snapshots["rank_snapshot"] = None
        snapshots["algorithm_version_snapshot"] = None
        snapshots["route_intent_bonus_snapshot"] = Decimal("0.00")

    return snapshots


@transaction.atomic
def express_interest_in_offer(
    *,
    offer: FreightOffer,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
    vehicle: Vehicle | None = None,
    invitation: FreightOfferInvitation | None = None,
    notes: str = "",
    actor=None,
) -> FreightOfferInterest:
    if offer.status != FreightOfferStatus.PUBLISHED.value:
        raise ValidationError({"offer": "Interesse só pode ser manifestado em ofertas publicadas."})
    if offer.is_expired:
        raise ValidationError({"offer": "Oferta expirada."})

    # Validate invitation belongs to this offer
    if invitation:
        if invitation.offer_id != offer.id:
            raise ValidationError({"invitation": "Convite não pertence a esta oferta."})

    # Propagate missing candidate fields from invitation.match_candidate and validate conflicts
    if invitation and invitation.match_candidate:
        candidate = invitation.match_candidate
        # carrier
        if carrier is None:
            carrier = candidate.carrier
        elif candidate.carrier is not None and carrier.id != candidate.carrier.id:
            raise ValidationError({"carrier": "Carrier informado difere do candidato da convite."})
        # driver
        if driver is None:
            driver = candidate.driver
        elif candidate.driver is not None and driver.id != candidate.driver.id:
            raise ValidationError({"driver": "Driver informado difere do candidato da convite."})
        # vehicle
        if vehicle is None:
            vehicle = candidate.vehicle
        elif candidate.vehicle is not None and vehicle.id != candidate.vehicle.id:
            raise ValidationError({"vehicle": "Vehicle informado difere do candidato da convite."})

    # Tenant isolation validation – recompute after possible propagation
    cand_org = carrier.organization if carrier else (driver.organization if driver else None)
    if not cand_org:
        raise ValidationError({"candidate": "Combinação de candidato inválida ou sem organização."})

    # Revalidate eligibility with possibly inferred entities
    if not check_candidate_eligibility(
        offer=offer, carrier=carrier, driver=driver, vehicle=vehicle
    ):
        raise ValidationError({"candidate": "Candidato não elegível para a oferta."})

    # Duplicity checks – using the final carrier/driver/vehicle values
    existing_active = FreightOfferInterest.objects.filter(
        offer=offer,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status=FreightOfferInterestStatus.ACTIVE.value,
    ).first()
    if existing_active:
        return existing_active

    from django.db.utils import IntegrityError

    try:
        with transaction.atomic():
            interest = FreightOfferInterest.objects.create(
                organization=cand_org,
                offer=offer,
                invitation=invitation,
                match_candidate=invitation.match_candidate if invitation else None,
                carrier=carrier,
                driver=driver,
                vehicle=vehicle,
                status=FreightOfferInterestStatus.ACTIVE.value,
                expressed_at=timezone.now(),
                notes=notes,
            )
    except IntegrityError:
        # Concurrent request already created it. Retrieve and return.
        existing_active = FreightOfferInterest.objects.filter(
            offer=offer,
            carrier=carrier,
            driver=driver,
            vehicle=vehicle,
            status=FreightOfferInterestStatus.ACTIVE.value,
        ).first()
        if existing_active:
            return existing_active
        raise

    record_audit_event(
        action="freight_interest_created",
        actor=actor,
        organization=offer.organization,
        target=interest,
        after={
            "id": str(interest.id),
            "offer_id": str(offer.id),
            "status": interest.status,
        },
    )

    record_marketplace_event(
        offer=offer,
        event_type=MarketplaceEventType.OFFER_INTEREST_EXPRESSED,
        actor=actor,
        carrier=carrier,
        driver=driver,
        metadata={"interest_id": str(interest.id)},
    )

    return interest


@transaction.atomic
def withdraw_interest(
    interest: FreightOfferInterest,
    *,
    actor=None,
) -> FreightOfferInterest:
    interest = (
        FreightOfferInterest.objects.select_for_update().select_related("offer").get(pk=interest.pk)
    )
    if interest.status != FreightOfferInterestStatus.ACTIVE.value:
        raise ValidationError({"status": "Apenas interesses ativos podem ser retirados."})

    # Enforce that selected candidates cannot withdraw directly
    is_selected = FreightOfferSelection.objects.filter(
        interest=interest,
        status__in=[
            FreightOfferSelectionStatus.PENDING_CONFIRMATION.value,
            FreightOfferSelectionStatus.CONFIRMED.value,
        ],
    ).exists()
    if is_selected:
        raise ValidationError(
            {"status": "Candidato já selecionado. Utilize a recusa ou cancelamento."}
        )

    interest.status = FreightOfferInterestStatus.WITHDRAWN.value
    interest.withdrawn_at = timezone.now()
    interest.save()

    record_audit_event(
        action="freight_interest_withdrawn",
        actor=actor,
        organization=interest.offer.organization,
        target=interest,
        after={
            "id": str(interest.id),
            "status": interest.status,
            "withdrawn_at": interest.withdrawn_at.isoformat(),
        },
    )

    record_marketplace_event(
        offer=interest.offer,
        event_type=MarketplaceEventType.OFFER_INTEREST_WITHDRAWN,
        actor=actor,
        carrier=interest.carrier,
        driver=interest.driver,
        metadata={"interest_id": str(interest.id)},
    )

    return interest


@transaction.atomic
def select_interested_candidate(
    interest: FreightOfferInterest,
    *,
    confirmation_expires_in_hours: int = 24,
    actor=None,
) -> FreightOfferSelection:
    offer = FreightOffer.objects.select_for_update().get(pk=interest.offer_id)
    if offer.status != FreightOfferStatus.PUBLISHED.value:
        raise ValidationError({"offer": "Seleção só pode ocorrer em ofertas publicadas."})
    if offer.is_expired:
        raise ValidationError({"offer": "Oferta expirada."})

    interest = FreightOfferInterest.objects.select_for_update().get(pk=interest.pk)
    if interest.status != FreightOfferInterestStatus.ACTIVE.value:
        raise ValidationError({"interest": "Interesse não está ativo."})

    # Validate eligibility at selection time
    if not check_candidate_eligibility(
        offer=offer,
        carrier=interest.carrier,
        driver=interest.driver,
        vehicle=interest.vehicle,
    ):
        raise ValidationError({"candidate": "Candidato não é mais elegível."})

    # Enforce only one active selection per offer
    active_selection_exists = FreightOfferSelection.objects.filter(
        offer=offer,
        status__in=[
            FreightOfferSelectionStatus.PENDING_CONFIRMATION.value,
            FreightOfferSelectionStatus.CONFIRMED.value,
        ],
    ).exists()
    if active_selection_exists:
        raise ValidationError(
            {"offer": "Já existe uma seleção ativa ou confirmada para esta oferta."}
        )

    snapshots = _build_candidate_snapshots(
        offer=offer,
        carrier=interest.carrier,
        driver=interest.driver,
        vehicle=interest.vehicle,
        interest=interest,
    )

    selection = FreightOfferSelection.objects.create(
        organization=offer.organization,
        offer=offer,
        interest=interest,
        selected_by=actor,
        selected_at=timezone.now(),
        status=FreightOfferSelectionStatus.PENDING_CONFIRMATION.value,
        confirmation_expires_at=timezone.now() + timedelta(hours=confirmation_expires_in_hours),
        **snapshots,
    )

    interest.status = FreightOfferInterestStatus.SELECTED.value
    interest.save()

    record_audit_event(
        action="freight_selection_created",
        actor=actor,
        organization=offer.organization,
        target=selection,
        after={
            "id": str(selection.id),
            "interest_id": str(interest.id),
            "status": selection.status,
        },
    )

    record_marketplace_event(
        offer=offer,
        event_type=MarketplaceEventType.OFFER_CANDIDATE_SELECTED,
        actor=actor,
        carrier=interest.carrier,
        driver=interest.driver,
        metadata={"selection_id": str(selection.id)},
    )

    return selection


@transaction.atomic
def cancel_selection(
    selection: FreightOfferSelection,
    *,
    reason: str = "",
    actor=None,
) -> FreightOfferSelection:
    selection = (
        FreightOfferSelection.objects.select_for_update()
        .select_related("offer", "interest")
        .get(pk=selection.pk)
    )
    if selection.status != FreightOfferSelectionStatus.PENDING_CONFIRMATION.value:
        raise ValidationError(
            {"status": "Apenas seleções pendentes de confirmação podem ser canceladas."}
        )

    selection.status = FreightOfferSelectionStatus.CANCELLED.value
    selection.cancelled_at = timezone.now()
    selection.cancel_reason = reason
    selection.save()

    # Restore interest back to ACTIVE
    interest = selection.interest
    interest.status = FreightOfferInterestStatus.ACTIVE.value
    interest.save()

    record_audit_event(
        action="freight_selection_cancelled",
        actor=actor,
        organization=selection.offer.organization,
        target=selection,
        after={
            "id": str(selection.id),
            "status": selection.status,
            "cancel_reason": reason,
        },
    )

    return selection


@transaction.atomic
def confirm_selection(
    selection: FreightOfferSelection,
    *,
    actor=None,
) -> FreightOfferSelection:
    selection = (
        FreightOfferSelection.objects.select_for_update()
        .select_related("offer", "interest")
        .get(pk=selection.pk)
    )
    # Apply expiration if needed
    apply_selection_expiration_if_needed(selection)

    # Idempotent handling: if already confirmed, ensure operation exists and return
    if selection.status == FreightOfferSelectionStatus.CONFIRMED.value:
        # Ensure operation exists (create if missing)
        from src.freights.application.operation_services import create_operation_from_selection
        create_operation_from_selection(
            selection_id=selection.id,
            actor=actor,
        )
        return selection

    if selection.status != FreightOfferSelectionStatus.PENDING_CONFIRMATION.value:
        raise ValidationError({"status": "Seleção não está pendente de confirmação."})


    offer = FreightOffer.objects.select_for_update().get(pk=selection.offer_id)
    interest = selection.interest

    # Revalidate eligibility at confirmation time
    if not check_candidate_eligibility(
        offer=offer,
        carrier=interest.carrier,
        driver=interest.driver,
        vehicle=interest.vehicle,
    ):
        raise ValidationError({"candidate": "Candidato não é mais elegível."})

    selection.status = FreightOfferSelectionStatus.CONFIRMED.value
    selection.confirmed_at = timezone.now()
    selection.save()

    interest.status = FreightOfferInterestStatus.SELECTED.value
    interest.save()

    # Dismiss/NOT_SELECTED other candidates now that it's confirmed
    FreightOfferInterest.objects.filter(
        offer=offer, status=FreightOfferInterestStatus.ACTIVE.value
    ).exclude(pk=interest.pk).update(status=FreightOfferInterestStatus.NOT_SELECTED.value)

    # Transition FreightOffer to CLOSED
    offer.status = FreightOfferStatus.CLOSED.value
    offer.save()

    # Record audit and marketplace event for selection confirmation (already present)
    record_audit_event(
        action="freight_selection_confirmed",
        actor=actor,
        organization=offer.organization,
        target=selection,
        after={
            "id": str(selection.id),
            "status": selection.status,
            "confirmed_at": selection.confirmed_at.isoformat(),
        },
    )

    record_marketplace_event(
        offer=offer,
        event_type=MarketplaceEventType.OFFER_SELECTION_CONFIRMED,
        actor=actor,
        carrier=interest.carrier,
        driver=interest.driver,
        metadata={"selection_id": str(selection.id)},
    )

    # ----- New: create FreightOperation within same transaction -----
    # Import locally to avoid circular dependency
    from src.freights.application.operation_services import create_operation_from_selection
    create_operation_from_selection(
        selection_id=selection.id,
        actor=actor,
    )

    return selection


@transaction.atomic
def decline_selection(
    selection: FreightOfferSelection,
    *,
    reason: SelectionDeclineReason,
    actor=None,
) -> FreightOfferSelection:
    selection = (
        FreightOfferSelection.objects.select_for_update()
        .select_related("offer", "interest")
        .get(pk=selection.pk)
    )
    if selection.status != FreightOfferSelectionStatus.PENDING_CONFIRMATION.value:
        raise ValidationError({"status": "Seleção não está pendente de confirmação."})

    selection.status = FreightOfferSelectionStatus.DECLINED.value
    selection.declined_at = timezone.now()
    selection.declined_reason = reason.value
    selection.save()

    # Candidate declined, interest moves to CANCELLED
    interest = selection.interest
    interest.status = FreightOfferInterestStatus.CANCELLED.value
    interest.save()

    record_audit_event(
        action="freight_selection_declined",
        actor=actor,
        organization=selection.offer.organization,
        target=selection,
        after={
            "id": str(selection.id),
            "status": selection.status,
            "declined_reason": reason.value,
        },
    )

    record_marketplace_event(
        offer=selection.offer,
        event_type=MarketplaceEventType.OFFER_SELECTION_DECLINED,
        actor=actor,
        carrier=interest.carrier,
        driver=interest.driver,
        metadata={
            "selection_id": str(selection.id),
            "declined_reason": reason.value,
        },
    )

    return selection


def apply_selection_expiration_if_needed(
    selection: FreightOfferSelection,
) -> FreightOfferSelection:
    if selection.status != FreightOfferSelectionStatus.PENDING_CONFIRMATION.value:
        return selection

    if selection.confirmation_expires_at and selection.confirmation_expires_at <= timezone.now():
        with transaction.atomic():
            selection = FreightOfferSelection.objects.select_for_update().get(pk=selection.pk)
            if selection.status == FreightOfferSelectionStatus.PENDING_CONFIRMATION.value:
                selection.status = FreightOfferSelectionStatus.EXPIRED.value
                selection.save()

                interest = selection.interest
                interest.status = FreightOfferInterestStatus.ACTIVE.value
                interest.save()

                record_marketplace_event(
                    offer=selection.offer,
                    event_type=MarketplaceEventType.OFFER_SELECTION_EXPIRED,
                    carrier=interest.carrier,
                    driver=interest.driver,
                    metadata={"selection_id": str(selection.id)},
                )
    return selection
