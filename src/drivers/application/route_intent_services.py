from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.drivers.domain.route_intent_enums import (
    DriverRouteIntentSource,
    DriverRouteIntentStatus,
    DriverRouteIntentType,
    RouteIntentCargoPreference,
)
from src.drivers.domain.route_intent_state_machine import can_transition_route_intent
from src.drivers.infrastructure.django.models import Driver, DriverRouteIntent
from src.vehicles.domain.enums import VehicleCargoProfile
from src.vehicles.infrastructure.django.models import DriverVehicleAssignment, Vehicle


@dataclass(frozen=True)
class DriverRouteIntentData:
    organization: Any
    driver: Driver
    intent_type: DriverRouteIntentType
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    available_from: datetime
    available_until: datetime
    vehicle: Vehicle | None = None
    max_origin_deviation_km: Decimal | None = None
    max_destination_deviation_km: Decimal | None = None
    cargo_preference: RouteIntentCargoPreference | None = None
    source: DriverRouteIntentSource = DriverRouteIntentSource.BACKOFFICE
    notes: str = ""


def _normalize_state(state: str) -> str:
    return (state or "").strip().upper()


def _normalize_city(city: str) -> str:
    return (city or "").strip()


def _validate_availability_window(*, available_from: datetime, available_until: datetime) -> None:
    if available_until <= available_from:
        raise ValidationError(
            {"available_until": "Disponível até deve ser posterior a disponível de."}
        )


def _validate_driver_scope(*, organization_id, driver: Driver) -> None:
    if driver.organization_id != organization_id:
        raise ValidationError({"driver": "Motorista fora da organização."})


def _validate_vehicle_assignment(*, driver: Driver, vehicle: Vehicle | None) -> None:
    if vehicle is None:
        return
    if vehicle.organization_id != driver.organization_id:
        raise ValidationError({"vehicle": "Veículo fora da organização do motorista."})
    active_assignment = DriverVehicleAssignment.objects.filter(
        driver=driver,
        vehicle=vehicle,
        active=True,
    ).exists()
    if not active_assignment:
        raise ValidationError(
            {"vehicle": "Veículo deve possuir vínculo operacional ativo com o motorista."}
        )


def _validate_refrigerated_preference(
    *,
    cargo_preference: RouteIntentCargoPreference | None,
    vehicle: Vehicle | None,
) -> None:
    if cargo_preference != RouteIntentCargoPreference.REFRIGERATED_CARGO:
        return
    if vehicle is None:
        return
    if vehicle.cargo_profile not in {
        VehicleCargoProfile.REFRIGERATED_CARGO.value,
        VehicleCargoProfile.BOTH.value,
    } and not vehicle.refrigerated:
        raise ValidationError(
            {"cargo_preference": "Veículo vinculado não suporta capacidade refrigerada."}
        )


def _build_refrigeration_snapshot(vehicle: Vehicle | None) -> dict[str, Any]:
    if vehicle is None:
        return {}
    profile = getattr(vehicle, "refrigeration_profile", None)
    if not profile:
        return {
            "vehicle_id": str(vehicle.id),
            "refrigerated": vehicle.refrigerated,
            "cargo_profile": vehicle.cargo_profile,
        }
    return {
        "vehicle_id": str(vehicle.id),
        "refrigerated": vehicle.refrigerated,
        "cargo_profile": vehicle.cargo_profile,
        "temperature_min_c": str(profile.temperature_min_c),
        "temperature_max_c": str(profile.temperature_max_c),
        "default_setpoint_c": (
            str(profile.default_setpoint_c) if profile.default_setpoint_c is not None else ""
        ),
    }


def _intent_audit_payload(intent: DriverRouteIntent) -> dict[str, Any]:
    return {
        "id": str(intent.id),
        "driver_id": str(intent.driver_id),
        "vehicle_id": str(intent.vehicle_id) if intent.vehicle_id else "",
        "intent_type": intent.intent_type,
        "status": intent.status,
        "origin": f"{intent.origin_city}/{intent.origin_state}",
        "destination": f"{intent.destination_city}/{intent.destination_state}",
        "available_from": intent.available_from.isoformat() if intent.available_from else "",
        "available_until": intent.available_until.isoformat() if intent.available_until else "",
    }


@transaction.atomic
def _transition_intent(
    intent: DriverRouteIntent,
    *,
    target: DriverRouteIntentStatus,
    actor=None,
    audit_action: str,
    before: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DriverRouteIntent:
    current = DriverRouteIntentStatus(intent.status)
    if not can_transition_route_intent(current=current, target=target):
        raise ValidationError({"status": f"Transição inválida: {current.value} → {target.value}."})
    if before is None:
        before = _intent_audit_payload(intent)
    intent.status = target.value
    intent.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action=audit_action,
        actor=actor,
        organization=intent.organization,
        target=intent,
        before=before,
        after=_intent_audit_payload(intent),
        metadata=metadata or {},
    )
    return intent


def apply_route_intent_expiration_if_needed(
    intent: DriverRouteIntent,
    *,
    actor=None,
) -> DriverRouteIntent:
    if intent.status != DriverRouteIntentStatus.ACTIVE.value:
        return intent
    if intent.available_until > timezone.now():
        return intent
    before = _intent_audit_payload(intent)
    return _transition_intent(
        intent,
        target=DriverRouteIntentStatus.EXPIRED,
        actor=actor,
        audit_action="driver_route_intent_expired",
        before=before,
    )


def get_active_route_intents_for_driver(
    driver: Driver,
    *,
    apply_expiration: bool = True,
) -> list[DriverRouteIntent]:
    intents = list(
        DriverRouteIntent.objects.filter(
            driver=driver,
            status=DriverRouteIntentStatus.ACTIVE.value,
        )
        .select_related("vehicle", "organization")
        .order_by("available_from")
    )
    if not apply_expiration:
        return intents
    active: list[DriverRouteIntent] = []
    now = timezone.now()
    for intent in intents:
        intent = apply_route_intent_expiration_if_needed(intent)
        if intent.status == DriverRouteIntentStatus.ACTIVE.value and intent.available_until > now:
            active.append(intent)
    return active


def get_active_route_intents_for_vehicle(
    vehicle,
    *,
    apply_expiration: bool = True,
) -> list[DriverRouteIntent]:
    intents = list(
        DriverRouteIntent.objects.filter(
            vehicle=vehicle,
            status=DriverRouteIntentStatus.ACTIVE.value,
        )
        .select_related("driver", "vehicle", "organization")
        .order_by("available_from")
    )
    if not apply_expiration:
        return intents
    active: list[DriverRouteIntent] = []
    now = timezone.now()
    for intent in intents:
        intent = apply_route_intent_expiration_if_needed(intent)
        if intent.status == DriverRouteIntentStatus.ACTIVE.value and intent.available_until > now:
            active.append(intent)
    return active


@transaction.atomic
def create_driver_route_intent(
    *,
    data: DriverRouteIntentData,
    actor=None,
) -> DriverRouteIntent:
    _validate_driver_scope(organization_id=data.organization.id, driver=data.driver)
    _validate_availability_window(
        available_from=data.available_from,
        available_until=data.available_until,
    )
    _validate_vehicle_assignment(driver=data.driver, vehicle=data.vehicle)
    _validate_refrigerated_preference(
        cargo_preference=data.cargo_preference,
        vehicle=data.vehicle,
    )
    intent = DriverRouteIntent(
        organization=data.organization,
        driver=data.driver,
        vehicle=data.vehicle,
        intent_type=data.intent_type.value,
        origin_city=_normalize_city(data.origin_city),
        origin_state=_normalize_state(data.origin_state),
        destination_city=_normalize_city(data.destination_city),
        destination_state=_normalize_state(data.destination_state),
        available_from=data.available_from,
        available_until=data.available_until,
        max_origin_deviation_km=data.max_origin_deviation_km,
        max_destination_deviation_km=data.max_destination_deviation_km,
        cargo_preference=data.cargo_preference.value if data.cargo_preference else "",
        refrigeration_snapshot=_build_refrigeration_snapshot(data.vehicle),
        status=DriverRouteIntentStatus.DRAFT.value,
        source=data.source.value,
        notes=data.notes.strip(),
    )
    intent.full_clean()
    intent.save()
    record_audit_event(
        action="driver_route_intent_created",
        actor=actor,
        organization=intent.organization,
        target=intent,
        after=_intent_audit_payload(intent),
    )
    return intent


@transaction.atomic
def update_driver_route_intent(
    intent: DriverRouteIntent,
    *,
    data: DriverRouteIntentData,
    actor=None,
) -> DriverRouteIntent:
    if intent.status != DriverRouteIntentStatus.DRAFT.value:
        raise ValidationError({"status": "Somente rascunhos podem ser editados."})
    _validate_driver_scope(organization_id=intent.organization_id, driver=data.driver)
    _validate_availability_window(
        available_from=data.available_from,
        available_until=data.available_until,
    )
    _validate_vehicle_assignment(driver=data.driver, vehicle=data.vehicle)
    _validate_refrigerated_preference(
        cargo_preference=data.cargo_preference,
        vehicle=data.vehicle,
    )
    before = _intent_audit_payload(intent)
    intent.driver = data.driver
    intent.vehicle = data.vehicle
    intent.intent_type = data.intent_type.value
    intent.origin_city = _normalize_city(data.origin_city)
    intent.origin_state = _normalize_state(data.origin_state)
    intent.destination_city = _normalize_city(data.destination_city)
    intent.destination_state = _normalize_state(data.destination_state)
    intent.available_from = data.available_from
    intent.available_until = data.available_until
    intent.max_origin_deviation_km = data.max_origin_deviation_km
    intent.max_destination_deviation_km = data.max_destination_deviation_km
    intent.cargo_preference = data.cargo_preference.value if data.cargo_preference else ""
    intent.refrigeration_snapshot = _build_refrigeration_snapshot(data.vehicle)
    intent.notes = data.notes.strip()
    intent.full_clean()
    intent.save()
    record_audit_event(
        action="driver_route_intent_updated",
        actor=actor,
        organization=intent.organization,
        target=intent,
        before=before,
        after=_intent_audit_payload(intent),
    )
    return intent


@transaction.atomic
def activate_driver_route_intent(
    intent: DriverRouteIntent,
    *,
    actor=None,
) -> DriverRouteIntent:
    intent = DriverRouteIntent.objects.select_for_update().select_related(
        "driver", "organization"
    ).get(pk=intent.pk)
    if intent.status != DriverRouteIntentStatus.DRAFT.value:
        raise ValidationError({"status": "Somente rascunhos podem ser ativados."})
    if intent.available_until <= timezone.now():
        raise ValidationError({"available_until": "Janela de disponibilidade já encerrada."})
    _validate_vehicle_assignment(driver=intent.driver, vehicle=intent.vehicle)
    before = _intent_audit_payload(intent)
    return _transition_intent(
        intent,
        target=DriverRouteIntentStatus.ACTIVE,
        actor=actor,
        audit_action="driver_route_intent_activated",
        before=before,
    )


@transaction.atomic
def cancel_driver_route_intent(
    intent: DriverRouteIntent,
    *,
    actor=None,
    reason: str = "",
) -> DriverRouteIntent:
    intent = DriverRouteIntent.objects.select_for_update().get(pk=intent.pk)
    if intent.status not in {
        DriverRouteIntentStatus.DRAFT.value,
        DriverRouteIntentStatus.ACTIVE.value,
    }:
        raise ValidationError({"status": "Intenção não pode ser cancelada neste estado."})
    before = _intent_audit_payload(intent)
    intent.cancel_reason = reason.strip()
    intent.cancelled_by = actor
    intent.cancelled_at = timezone.now()
    intent.save(update_fields=["cancel_reason", "cancelled_by", "cancelled_at", "updated_at"])
    return _transition_intent(
        intent,
        target=DriverRouteIntentStatus.CANCELLED,
        actor=actor,
        audit_action="driver_route_intent_cancelled",
        before=before,
        metadata={"reason": reason.strip()},
    )
