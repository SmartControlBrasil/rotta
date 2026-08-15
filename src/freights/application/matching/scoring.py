from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.application.route_compatibility import (
    evaluate_route_intent_compatibility,
    get_active_route_intents_for_driver,
)
from src.drivers.domain.enums import DriverAvailabilityStatus
from src.drivers.domain.route_intent_enums import RouteIntentCompatibilityLevel
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.matching.constants import (
    MATCHING_ALGORITHM_VERSION,
    MATCHING_WEIGHTS,
    NEUTRAL_SCORE_WHEN_UNAVAILABLE,
    ROUTE_INTENT_BONUS_EXACT,
    ROUTE_INTENT_BONUS_PARTIAL,
)
from src.freights.application.matching.eligibility import EligibilityResult
from src.freights.domain.enums import FreightCargoProfile
from src.freights.domain.matching_enums import MatchEligibilityStatus
from src.freights.infrastructure.django.models import FreightOffer
from src.vehicles.domain.enums import VehicleCargoProfile, VehicleOperationalStatus
from src.vehicles.infrastructure.django.models import RefrigerationProfile, Vehicle


@dataclass
class ScoreBreakdown:
    distance_score: Decimal | None = None
    compliance_score: Decimal | None = None
    vehicle_score: Decimal | None = None
    cargo_score: Decimal | None = None
    temperature_score: Decimal | None = None
    availability_score: Decimal | None = None
    performance_score: Decimal | None = None
    price_score: Decimal | None = None
    route_intent_score: Decimal | None = None
    total_score: Decimal | None = None
    explanation: dict = field(default_factory=dict)

    def to_model_fields(self) -> dict:
        return {
            "distance_score": self.distance_score,
            "compliance_score": self.compliance_score,
            "vehicle_score": self.vehicle_score,
            "cargo_score": self.cargo_score,
            "temperature_score": self.temperature_score,
            "availability_score": self.availability_score,
            "performance_score": self.performance_score,
            "price_score": self.price_score,
            "total_score": self.total_score,
            "score_explanation": self.explanation,
        }


def _score(value: float) -> Decimal:
    bounded = max(0.0, min(100.0, value))
    return Decimal(str(round(bounded, 2)))


def compute_scores(
    *,
    offer: FreightOffer,
    eligibility: EligibilityResult,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
    vehicle: Vehicle | None = None,
    refrigeration: RefrigerationProfile | None = None,
    distance_to_pickup_km: Decimal | None = None,
    active_intents: list = None,
    algorithm_version: str = MATCHING_ALGORITHM_VERSION,
) -> ScoreBreakdown:
    breakdown = ScoreBreakdown()
    if eligibility.status == MatchEligibilityStatus.INELIGIBLE:
        breakdown.explanation = {"eligible": False, "reason": "INELIGIBLE"}
        return breakdown

    blocking_reasons = [reason for reason in eligibility.reasons if reason.blocking]
    compliance_value = 100.0 if not blocking_reasons else 0.0
    breakdown.compliance_score = _score(compliance_value)
    breakdown.explanation["compliance"] = {
        "score": float(breakdown.compliance_score),
        "reason": "COMPLIANT" if compliance_value == 100 else "NON_COMPLIANT_SIGNALS",
    }

    if distance_to_pickup_km is None:
        breakdown.distance_score = _score(NEUTRAL_SCORE_WHEN_UNAVAILABLE)
        breakdown.explanation["distance"] = {
            "score": float(breakdown.distance_score),
            "reason": "Geolocalização indisponível — score neutro",
            "available": False,
        }
    else:
        distance = float(distance_to_pickup_km)
        distance_value = max(0.0, 100.0 - min(distance, 100.0))
        breakdown.distance_score = _score(distance_value)
        breakdown.explanation["distance"] = {
            "score": float(breakdown.distance_score),
            "reason": f"{distance:.1f} km from pickup",
            "available": True,
        }

    snapshot = offer.premises_snapshot
    if vehicle:
        required_type = snapshot.get("vehicle_type_required") or ""
        required_body = snapshot.get("body_type_required") or ""
        type_match = not required_type or vehicle.vehicle_type == required_type
        body_match = not required_body or vehicle.body_type == required_body
        vehicle_value = 100.0 if type_match and body_match else 40.0
        breakdown.vehicle_score = _score(vehicle_value)
        breakdown.explanation["vehicle"] = {
            "score": float(breakdown.vehicle_score),
            "reason": "required vehicle/body matched"
            if vehicle_value == 100
            else "partial vehicle/body mismatch",
        }
    elif carrier and not vehicle:
        breakdown.vehicle_score = _score(NEUTRAL_SCORE_WHEN_UNAVAILABLE)
        breakdown.explanation["vehicle"] = {
            "score": float(breakdown.vehicle_score),
            "reason": "Carrier-only candidate — vehicle not evaluated",
            "available": False,
        }

    cargo_profile = snapshot.get("cargo_profile", "")
    if vehicle:
        if cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
            cargo_value = (
                100.0
                if vehicle.cargo_profile
                in {VehicleCargoProfile.REFRIGERATED_CARGO.value, VehicleCargoProfile.BOTH.value}
                or vehicle.refrigerated
                else 0.0
            )
        else:
            cargo_value = 100.0
        breakdown.cargo_score = _score(cargo_value)
        breakdown.explanation["cargo"] = {
            "score": float(breakdown.cargo_score),
            "reason": f"cargo_profile={cargo_profile}",
        }
    elif carrier:
        breakdown.cargo_score = _score(100.0)
        breakdown.explanation["cargo"] = {
            "score": float(breakdown.cargo_score),
            "reason": "Carrier cargo profile pre-validated",
        }

    if cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value and vehicle:
        if refrigeration:
            breakdown.temperature_score = _score(100.0)
            breakdown.explanation["temperature"] = {
                "score": 100.0,
                "reason": (
                    f"range {refrigeration.temperature_min_c}..{refrigeration.temperature_max_c}°C"
                ),
            }
        else:
            breakdown.temperature_score = _score(0.0)
            breakdown.explanation["temperature"] = {
                "score": 0.0,
                "reason": "No refrigeration profile",
            }
    elif cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value and carrier and not vehicle:
        breakdown.temperature_score = _score(NEUTRAL_SCORE_WHEN_UNAVAILABLE)
        breakdown.explanation["temperature"] = {
            "score": float(breakdown.temperature_score),
            "reason": "Carrier-only — thermal score neutral",
            "available": False,
        }

    availability_parts: list[float] = []
    availability_notes: list[str] = []
    if driver:
        if driver.availability_status == DriverAvailabilityStatus.AVAILABLE.value:
            availability_parts.append(100.0)
        elif driver.availability_status == DriverAvailabilityStatus.PAUSED.value:
            availability_parts.append(70.0)
        else:
            availability_parts.append(20.0)
        availability_notes.append(f"driver={driver.availability_status}")
    if vehicle:
        if vehicle.operational_status == VehicleOperationalStatus.AVAILABLE.value:
            availability_parts.append(100.0)
        elif vehicle.operational_status == VehicleOperationalStatus.ASSIGNED.value:
            availability_parts.append(75.0)
        else:
            availability_parts.append(25.0)
        availability_notes.append(f"vehicle={vehicle.operational_status}")
    if availability_parts:
        breakdown.availability_score = _score(sum(availability_parts) / len(availability_parts))
        breakdown.explanation["availability"] = {
            "score": float(breakdown.availability_score),
            "reason": ", ".join(availability_notes),
        }
    elif carrier:
        breakdown.availability_score = _score(NEUTRAL_SCORE_WHEN_UNAVAILABLE)
        breakdown.explanation["availability"] = {
            "score": float(breakdown.availability_score),
            "reason": "Carrier-only — availability neutral",
            "available": False,
        }

    breakdown.explanation["performance"] = {
        "available": False,
        "reason": "Performance history not implemented in v1",
    }
    breakdown.explanation["price"] = {
        "available": False,
        "reason": "Price/bid comparison not implemented in v1",
    }

    # Route Intent Score calculation
    route_intent_compatibility = "UNKNOWN"
    route_intent_bonus_val = 0.0

    if driver:
        if active_intents is None:
            active_intents = get_active_route_intents_for_driver(driver)
        # Filter intents applicable to the candidate's vehicle (if any) and match offer tenant
        applicable_intents = []
        for intent in active_intents:
            if intent.organization_id != offer.organization_id:
                continue
            if intent.vehicle_id and (not vehicle or intent.vehicle_id != vehicle.id):
                continue
            applicable_intents.append(intent)

        if not applicable_intents:
            breakdown.route_intent_score = _score(NEUTRAL_SCORE_WHEN_UNAVAILABLE)
            breakdown.explanation["route_intent"] = {
                "score": NEUTRAL_SCORE_WHEN_UNAVAILABLE,
                "compatibility": "UNKNOWN",
                "bonus": 0.0,
                "reason": "No active route preference",
            }
        else:
            best_score = -1.0
            best_compatibility = "UNKNOWN"
            best_intent = None
            now_time = timezone.now()

            for intent in applicable_intents:
                comp_result = evaluate_route_intent_compatibility(
                    offer=offer,
                    route_intent=intent,
                    reference_time=now_time,
                )
                if comp_result.level == RouteIntentCompatibilityLevel.EXACT:
                    score_val = 100.0
                elif comp_result.level == RouteIntentCompatibilityLevel.PARTIAL:
                    score_val = 75.0
                elif comp_result.level == RouteIntentCompatibilityLevel.UNKNOWN:
                    score_val = 50.0
                else:
                    score_val = 0.0

                if score_val > best_score:
                    best_score = score_val
                    best_compatibility = comp_result.level.value
                    best_intent = intent

            breakdown.route_intent_score = _score(best_score)
            route_intent_compatibility = best_compatibility

            if route_intent_compatibility == "EXACT":
                route_intent_bonus_val = ROUTE_INTENT_BONUS_EXACT
            elif route_intent_compatibility == "PARTIAL":
                route_intent_bonus_val = ROUTE_INTENT_BONUS_PARTIAL
            else:
                route_intent_bonus_val = 0.0

            if best_intent:
                breakdown.explanation["route_intent"] = {
                    "score": float(breakdown.route_intent_score),
                    "compatibility": best_compatibility,
                    "bonus": route_intent_bonus_val,
                    "intent_type": best_intent.intent_type,
                    "origin": f"{best_intent.origin_city}/{best_intent.origin_state}",
                    "destination": (
                        f"{best_intent.destination_city}/{best_intent.destination_state}"
                    ),
                    "reason": (
                        "Freight route matches driver's active intent."
                        if best_compatibility != "INCOMPATIBLE"
                        else "No matching route preference."
                    ),
                    "route_intent_id": str(best_intent.id),
                }
            else:
                breakdown.explanation["route_intent"] = {
                    "score": float(breakdown.route_intent_score),
                    "compatibility": best_compatibility,
                    "bonus": route_intent_bonus_val,
                    "reason": "No active route preference",
                }
    else:
        breakdown.route_intent_score = None
        breakdown.explanation["route_intent"] = {
            "available": False,
            "bonus": 0.0,
            "reason": "Carrier-only candidate — route intent not evaluated",
        }

    weighted_total = 0.0
    weight_sum = 0.0
    component_map = {
        "distance": breakdown.distance_score,
        "compliance": breakdown.compliance_score,
        "vehicle": breakdown.vehicle_score,
        "cargo": breakdown.cargo_score,
        "temperature": breakdown.temperature_score,
        "availability": breakdown.availability_score,
    }

    if algorithm_version == "v2":
        component_map["route_intent"] = breakdown.route_intent_score
        weights_dict = {**MATCHING_WEIGHTS, "route_intent": 0.10}
    else:
        weights_dict = MATCHING_WEIGHTS

    for key, weight in weights_dict.items():
        if key in {"performance", "price"}:
            continue
        value = component_map.get(key)
        if value is None:
            continue
        weighted_total += float(value) * weight
        weight_sum += weight

    if weight_sum > 0:
        base_match_score = weighted_total / weight_sum
    else:
        base_match_score = 0.0

    if algorithm_version == "v2.1":
        final_score = max(0.0, min(100.0, base_match_score + route_intent_bonus_val))
        breakdown.total_score = Decimal(str(round(final_score, 2)))
        breakdown.explanation["base_score"] = float(_score(base_match_score))
        breakdown.explanation["route_intent"]["bonus"] = route_intent_bonus_val
        breakdown.explanation["final_score"] = float(breakdown.total_score)
    else:
        breakdown.total_score = _score(base_match_score)

    breakdown.explanation["total"] = {
        "score": float(breakdown.total_score) if breakdown.total_score is not None else None,
        "weights_used": {
            key: weights_dict[key] for key in component_map if component_map[key] is not None
        },
    }
    return breakdown
