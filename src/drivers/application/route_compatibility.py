from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from src.drivers.domain.route_intent_enums import (
    DriverRouteIntentStatus,
    RouteIntentCargoPreference,
    RouteIntentCompatibilityLevel,
)
from src.drivers.infrastructure.django.models import DriverRouteIntent
from src.drivers.application.route_intent_services import apply_route_intent_expiration_if_needed
from src.freights.infrastructure.django.models import FreightOffer


@dataclass(frozen=True)
class RouteIntentCompatibilityResult:
    level: RouteIntentCompatibilityLevel
    reasons: list[str] = field(default_factory=list)


def _normalize_state(value: str) -> str:
    return (value or "").strip().upper()


def _normalize_city(value: str) -> str:
    return (value or "").strip().casefold()


def _location_tuple(city: str, state: str) -> tuple[str, str]:
    return (_normalize_city(city), _normalize_state(state))


def _offer_route(offer: FreightOffer) -> tuple[tuple[str, str], tuple[str, str]]:
    snapshot = offer.premises_snapshot or {}
    pickup = snapshot.get("pickup") or {}
    delivery = snapshot.get("delivery") or {}
    return (
        _location_tuple(pickup.get("city", ""), pickup.get("state", "")),
        _location_tuple(delivery.get("city", ""), delivery.get("state", "")),
    )


def _cargo_compatible(*, offer: FreightOffer, intent: DriverRouteIntent) -> bool:
    if not intent.cargo_preference:
        return True
    offer_profile = (offer.premises_snapshot or {}).get("cargo_profile", "")
    preference = RouteIntentCargoPreference(intent.cargo_preference)
    if preference == RouteIntentCargoPreference.BOTH:
        return True
    if preference == RouteIntentCargoPreference.DRY_CARGO:
        return offer_profile in {"", "DRY_CARGO"}
    if preference == RouteIntentCargoPreference.REFRIGERATED_CARGO:
        return offer_profile == "REFRIGERATED_CARGO"
    return True


def _within_intent_window(*, intent: DriverRouteIntent, reference: datetime | None = None) -> bool:
    now = reference or timezone.now()
    return intent.available_from <= now <= intent.available_until


def evaluate_route_intent_compatibility(
    *,
    offer: FreightOffer,
    route_intent: DriverRouteIntent,
    reference_time: datetime | None = None,
) -> RouteIntentCompatibilityResult:
    reasons: list[str] = []
    route_intent = apply_route_intent_expiration_if_needed(route_intent)
    if route_intent.status != DriverRouteIntentStatus.ACTIVE.value:
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.INCOMPATIBLE,
            reasons=["route_intent_not_active"],
        )
    if not _within_intent_window(intent=route_intent, reference=reference_time):
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.INCOMPATIBLE,
            reasons=["outside_availability_window"],
        )
    if not _cargo_compatible(offer=offer, intent=route_intent):
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.INCOMPATIBLE,
            reasons=["cargo_profile_incompatible"],
        )

    offer_origin, offer_destination = _offer_route(offer)
    intent_origin = _location_tuple(route_intent.origin_city, route_intent.origin_state)
    intent_destination = _location_tuple(
        route_intent.destination_city,
        route_intent.destination_state,
    )

    if not all(offer_origin) or not all(offer_destination):
        reasons.append("offer_route_incomplete")
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.UNKNOWN,
            reasons=reasons,
        )
    if not all(intent_origin) or not all(intent_destination):
        reasons.append("intent_route_incomplete")
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.UNKNOWN,
            reasons=reasons,
        )

    if offer_origin == intent_origin and offer_destination == intent_destination:
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.EXACT,
            reasons=["origin_and_destination_match"],
        )

    if offer_origin == intent_origin and offer_destination[1] == intent_destination[1]:
        if offer_destination[0] != intent_destination[0]:
            return RouteIntentCompatibilityResult(
                level=RouteIntentCompatibilityLevel.PARTIAL,
                reasons=["origin_match_destination_city_differs_same_state"],
            )

    if offer_origin == intent_origin:
        return RouteIntentCompatibilityResult(
            level=RouteIntentCompatibilityLevel.PARTIAL,
            reasons=["origin_match_only"],
        )

    return RouteIntentCompatibilityResult(
        level=RouteIntentCompatibilityLevel.INCOMPATIBLE,
        reasons=["route_mismatch"],
    )


from src.drivers.application.route_intent_services import (  # noqa: E402
    get_active_route_intents_for_driver,
)

__all__ = [
    "RouteIntentCompatibilityResult",
    "RouteIntentCompatibilityLevel",
    "evaluate_route_intent_compatibility",
    "get_active_route_intents_for_driver",
]
