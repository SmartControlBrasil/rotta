from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.freights.application.matching.candidate_generation import iter_candidate_specs
from src.freights.application.matching.constants import MATCHING_ALGORITHM_VERSION
from src.freights.application.matching.eligibility import (
    evaluate_carrier_eligibility,
    evaluate_driver_eligibility,
    evaluate_private_target_access,
    evaluate_vehicle_eligibility,
    load_private_target_ids,
    merge_eligibility_results,
    validate_candidate_shape,
)
from src.freights.application.matching.ranking import assign_rank_positions
from src.freights.application.matching.scoring import compute_scores
from src.freights.application.offer_services import apply_offer_expiration_if_needed
from src.freights.domain.matching_enums import MatchEligibilityStatus
from src.freights.domain.offer_enums import FreightOfferStatus
from src.freights.infrastructure.django.models import (
    FreightMatchCandidate,
    FreightMatchGeneration,
    FreightOffer,
)


def _ensure_offer_ready_for_matching(offer: FreightOffer) -> None:
    offer = apply_offer_expiration_if_needed(offer)
    if offer.status not in {
        FreightOfferStatus.PUBLISHED.value,
        FreightOfferStatus.PAUSED.value,
    }:
        raise ValidationError(
            {"status": "Matching disponível apenas para ofertas publicadas/pausadas."}
        )


@transaction.atomic
def generate_match_candidates_for_offer(
    offer: FreightOffer,
    *,
    actor=None,
    regenerate: bool = False,
) -> FreightMatchGeneration:
    offer = (
        FreightOffer.objects.select_for_update()
        .select_related("organization", "freight_request")
        .prefetch_related("targets")
        .get(pk=offer.pk)
    )
    _ensure_offer_ready_for_matching(offer)

    current = offer.match_generations.filter(is_current=True).first()
    if current and not regenerate:
        if current.algorithm_version == MATCHING_ALGORITHM_VERSION:
            return current

    if current:
        FreightMatchGeneration.objects.filter(offer=offer, is_current=True).update(is_current=False)

    next_number = (
        offer.match_generations.order_by("-generation_number")
        .values_list("generation_number", flat=True)
        .first()
        or 0
    ) + 1

    generation = FreightMatchGeneration.objects.create(
        offer=offer,
        organization=offer.organization,
        algorithm_version=MATCHING_ALGORITHM_VERSION,
        generation_number=next_number,
        is_current=True,
        generated_by=actor,
    )

    target_carrier_ids, target_driver_ids = load_private_target_ids(offer)
    specs = iter_candidate_specs(offer=offer)
    built: list[FreightMatchCandidate] = []
    now = timezone.now()

    driver_ids = [spec.driver.id for spec in specs if spec.driver]
    intents_by_driver = {}
    if driver_ids:
        from src.drivers.application.route_intent_services import (
            apply_route_intent_expiration_if_needed,
        )
        from src.drivers.domain.route_intent_enums import DriverRouteIntentStatus
        from src.drivers.infrastructure.django.models import DriverRouteIntent

        bulk_intents = list(
            DriverRouteIntent.objects.filter(
                driver_id__in=driver_ids,
                status=DriverRouteIntentStatus.ACTIVE.value,
            )
            .select_related("vehicle", "organization")
            .order_by("available_from")
        )
        for intent in bulk_intents:
            intent = apply_route_intent_expiration_if_needed(intent)
            if (
                intent.status == DriverRouteIntentStatus.ACTIVE.value
                and intent.available_until > now
            ):
                intents_by_driver.setdefault(intent.driver_id, []).append(intent)

    for spec in specs:
        shape = validate_candidate_shape(
            carrier=spec.carrier,
            driver=spec.driver,
            vehicle=spec.vehicle,
        )
        results = [shape]
        if spec.carrier:
            results.append(evaluate_carrier_eligibility(offer=offer, carrier=spec.carrier))
        if spec.driver:
            results.append(evaluate_driver_eligibility(offer=offer, driver=spec.driver))
        refrigeration = None
        if spec.vehicle:
            refrigeration = getattr(spec.vehicle, "refrigeration_profile", None)
            results.append(
                evaluate_vehicle_eligibility(
                    offer=offer,
                    vehicle=spec.vehicle,
                    refrigeration=refrigeration,
                )
            )
        results.append(
            evaluate_private_target_access(
                offer=offer,
                carrier=spec.carrier,
                driver=spec.driver,
                target_carrier_ids=target_carrier_ids,
                target_driver_ids=target_driver_ids,
            )
        )
        eligibility = merge_eligibility_results(*results)
        driver_intents = intents_by_driver.get(spec.driver.id) if spec.driver else None
        scores = compute_scores(
            offer=offer,
            eligibility=eligibility,
            carrier=spec.carrier,
            driver=spec.driver,
            vehicle=spec.vehicle,
            refrigeration=refrigeration,
            distance_to_pickup_km=None,
            active_intents=driver_intents,
            algorithm_version=MATCHING_ALGORITHM_VERSION,
        )
        candidate = FreightMatchCandidate(
            generation=generation,
            offer=offer,
            organization=offer.organization,
            carrier=spec.carrier,
            driver=spec.driver,
            vehicle=spec.vehicle,
            eligibility_status=eligibility.status.value,
            eligibility_reasons=eligibility.to_json(),
            algorithm_version=MATCHING_ALGORITHM_VERSION,
            generated_at=now,
            **scores.to_model_fields(),
        )
        built.append(candidate)

    rankings = assign_rank_positions(candidates=built)
    for ranked in rankings:
        candidate = built[ranked.candidate_index]
        candidate.rank_position = ranked.rank_position

    FreightMatchCandidate.objects.bulk_create(built, batch_size=500)

    eligible_count = sum(
        1
        for candidate in built
        if candidate.eligibility_status == MatchEligibilityStatus.ELIGIBLE.value
    )
    generation.candidate_count = len(built)
    generation.eligible_count = eligible_count
    generation.ineligible_count = len(built) - eligible_count
    generation.save(
        update_fields=[
            "candidate_count",
            "eligible_count",
            "ineligible_count",
            "updated_at",
        ]
    )

    audit_action = (
        "freight_matching_regenerated" if regenerate or current else "freight_matching_generated"
    )
    record_audit_event(
        action=audit_action,
        actor=actor,
        organization=offer.organization,
        target=offer,
        metadata={
            "algorithm_version": MATCHING_ALGORITHM_VERSION,
            "generation_number": generation.generation_number,
            "candidate_count": generation.candidate_count,
            "eligible_count": generation.eligible_count,
            "ineligible_count": generation.ineligible_count,
        },
    )
    return generation


def get_current_match_candidates(offer: FreightOffer):
    generation = (
        offer.match_generations.filter(is_current=True)
        .prefetch_related(
            "candidates__carrier",
            "candidates__driver",
            "candidates__vehicle",
        )
        .first()
    )
    if not generation:
        return FreightMatchCandidate.objects.none()
    return generation.candidates.select_related("carrier", "driver", "vehicle").all()
