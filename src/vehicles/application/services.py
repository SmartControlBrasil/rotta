from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from src.audit.infrastructure.django.services import record_audit_event
from src.carriers.domain.enums import CarrierVehicleLinkType
from src.carriers.infrastructure.django.models import CarrierProfile, CarrierVehicleLink
from src.drivers.infrastructure.django.models import Driver
from src.organizations.infrastructure.django.models import Organization
from src.vehicles.domain.enums import (
    RefrigerationControlType,
    VehicleBodyType,
    VehicleCargoProfile,
    VehicleOperationalStatus,
    VehicleOwnershipType,
    VehicleStatus,
    VehicleType,
)
from src.vehicles.infrastructure.django.models import (
    DriverVehicleAssignment,
    RefrigerationProfile,
    Vehicle,
)


@dataclass(frozen=True)
class VehicleData:
    organization: Organization
    plate: str
    vehicle_type: VehicleType
    body_type: VehicleBodyType | str = ""
    cargo_profile: VehicleCargoProfile = VehicleCargoProfile.DRY_CARGO
    ownership_type: VehicleOwnershipType = VehicleOwnershipType.OWNED
    renavam: str = ""
    chassis: str = ""
    brand: str = ""
    model: str = ""
    year: int | None = None
    model_year: int | None = None
    color: str = ""
    state: str = ""
    capacity_weight_kg: Decimal | None = None
    gross_weight_kg: Decimal | None = None
    capacity_volume_m3: Decimal | None = None
    max_length_m: Decimal | None = None
    max_width_m: Decimal | None = None
    max_height_m: Decimal | None = None
    odometer_km: int | None = None
    refrigerated: bool = False
    closed_box: bool = False
    open_body: bool = False
    tail_lift: bool = False
    helper_available: bool = False
    hazardous_compatible: bool = False
    status: VehicleStatus = VehicleStatus.PENDING_APPROVAL
    operational_status: VehicleOperationalStatus = VehicleOperationalStatus.UNAVAILABLE


@dataclass(frozen=True)
class RefrigerationProfileData:
    has_refrigeration_unit: bool = True
    unit_manufacturer: str = ""
    unit_model: str = ""
    temperature_min_c: Decimal | None = None
    temperature_max_c: Decimal | None = None
    default_setpoint_c: Decimal | None = None
    control_type: RefrigerationControlType = RefrigerationControlType.DIGITAL
    last_maintenance_date: date | None = None
    next_maintenance_date: date | None = None


@transaction.atomic
def register_vehicle(
    *,
    data: VehicleData,
    refrigeration_data: RefrigerationProfileData | None = None,
    actor=None,
) -> Vehicle:
    vehicle = Vehicle(**data.__dict__)
    vehicle.full_clean()
    vehicle.save()
    if refrigeration_data and vehicle.cargo_profile in {
        VehicleCargoProfile.REFRIGERATED_CARGO,
        VehicleCargoProfile.BOTH,
    }:
        upsert_refrigeration_profile(
            vehicle=vehicle,
            data=refrigeration_data,
            actor=actor,
            create_event=False,
        )
    record_audit_event(
        action="vehicle_created",
        actor=actor,
        organization=vehicle.organization,
        target=vehicle,
        after=_vehicle_audit_payload(vehicle),
    )
    return vehicle


@transaction.atomic
def update_vehicle(vehicle: Vehicle, *, actor=None, **changes) -> Vehicle:
    before = _vehicle_audit_payload(vehicle)
    allowed_fields = {
        "plate",
        "vehicle_type",
        "body_type",
        "cargo_profile",
        "ownership_type",
        "renavam",
        "chassis",
        "brand",
        "model",
        "year",
        "model_year",
        "color",
        "state",
        "capacity_weight_kg",
        "gross_weight_kg",
        "capacity_volume_m3",
        "max_length_m",
        "max_width_m",
        "max_height_m",
        "odometer_km",
        "refrigerated",
        "closed_box",
        "open_body",
        "tail_lift",
        "helper_available",
        "hazardous_compatible",
        "status",
        "operational_status",
    }
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValidationError({field: "Campo não pode ser atualizado por este caso de uso."})
        setattr(vehicle, field, value)
    vehicle.full_clean()
    vehicle.save()
    record_audit_event(
        action="vehicle_updated",
        actor=actor,
        organization=vehicle.organization,
        target=vehicle,
        before=before,
        after=_vehicle_audit_payload(vehicle),
    )
    return vehicle


@transaction.atomic
def assign_driver_to_vehicle(
    *,
    driver: Driver,
    vehicle: Vehicle,
    valid_from: date,
    actor=None,
    primary: bool = False,
) -> DriverVehicleAssignment:
    assignment = DriverVehicleAssignment(
        driver=driver,
        vehicle=vehicle,
        valid_from=valid_from,
        primary=primary,
        active=True,
    )
    assignment.full_clean()
    assignment.save()
    record_audit_event(
        action="driver_vehicle_assigned",
        actor=actor,
        organization=driver.organization,
        target=assignment,
        after=_assignment_audit_payload(assignment),
    )
    return assignment


@transaction.atomic
def unassign_driver_vehicle(
    assignment: DriverVehicleAssignment,
    *,
    valid_until: date,
    actor=None,
) -> DriverVehicleAssignment:
    before = _assignment_audit_payload(assignment)
    if valid_until < assignment.valid_from:
        raise ValidationError({"valid_until": "Fim da vigência não pode ser anterior ao início."})
    assignment.active = False
    assignment.primary = False
    assignment.valid_until = valid_until
    assignment.full_clean()
    assignment.save(update_fields=["active", "primary", "valid_until", "updated_at"])
    record_audit_event(
        action="driver_vehicle_unassigned",
        actor=actor,
        organization=assignment.driver.organization,
        target=assignment,
        before=before,
        after=_assignment_audit_payload(assignment),
    )
    return assignment


@transaction.atomic
def change_vehicle_status(
    vehicle: Vehicle,
    *,
    status: VehicleStatus,
    actor=None,
    reason: str = "",
) -> Vehicle:
    before = _vehicle_audit_payload(vehicle)
    vehicle.status = status
    if status in {VehicleStatus.BLOCKED, VehicleStatus.SUSPENDED, VehicleStatus.INACTIVE}:
        vehicle.operational_status = VehicleOperationalStatus.UNAVAILABLE
    vehicle.full_clean()
    vehicle.save(update_fields=["status", "operational_status", "updated_at"])
    record_audit_event(
        action="vehicle_status_changed",
        actor=actor,
        organization=vehicle.organization,
        target=vehicle,
        before=before,
        after=_vehicle_audit_payload(vehicle),
        metadata={"status": status.value, "reason": reason},
    )
    return vehicle


@transaction.atomic
def change_vehicle_operational_status(
    vehicle: Vehicle,
    *,
    operational_status: VehicleOperationalStatus,
    actor=None,
    reason: str = "",
) -> Vehicle:
    before = _vehicle_audit_payload(vehicle)
    vehicle.operational_status = operational_status
    vehicle.full_clean()
    vehicle.save(update_fields=["operational_status", "updated_at"])
    record_audit_event(
        action="vehicle_operational_status_changed",
        actor=actor,
        organization=vehicle.organization,
        target=vehicle,
        before=before,
        after=_vehicle_audit_payload(vehicle),
        metadata={"operational_status": operational_status.value, "reason": reason},
    )
    return vehicle


@transaction.atomic
def upsert_refrigeration_profile(
    *,
    vehicle: Vehicle,
    data: RefrigerationProfileData,
    actor=None,
    create_event: bool = True,
) -> RefrigerationProfile:
    if vehicle.cargo_profile == VehicleCargoProfile.DRY_CARGO:
        raise ValidationError(
            {"cargo_profile": "Veículo de carga seca não pode receber perfil de refrigeração."}
        )
    if data.temperature_min_c is None or data.temperature_max_c is None:
        raise ValidationError(
            {
                "temperature_min_c": (
                    "Informe faixa térmica mínima e máxima para veículo refrigerado."
                )
            }
        )
    profile = RefrigerationProfile.objects.filter(vehicle=vehicle).first()
    if profile is None:
        profile = RefrigerationProfile(vehicle=vehicle)
        before = {}
    else:
        before = _refrigeration_audit_payload(profile)
    for field, value in data.__dict__.items():
        setattr(profile, field, value)
    profile.full_clean()
    profile.save()
    if create_event:
        record_audit_event(
            action="vehicle_refrigeration_updated",
            actor=actor,
            organization=vehicle.organization,
            target=vehicle,
            before=before,
            after=_refrigeration_audit_payload(profile),
        )
    return profile


@transaction.atomic
def link_vehicle_to_carrier(
    *,
    vehicle: Vehicle,
    carrier: CarrierProfile,
    link_type: CarrierVehicleLinkType = CarrierVehicleLinkType.OWNED,
    actor=None,
) -> CarrierVehicleLink:
    link, created = CarrierVehicleLink.objects.get_or_create(
        carrier=carrier,
        vehicle=vehicle,
        defaults={"active": True, "link_type": link_type.value},
    )
    if not created:
        link.active = True
        link.link_type = link_type.value
    link.full_clean()
    link.save()
    record_audit_event(
        action="vehicle_carrier_linked",
        actor=actor,
        organization=vehicle.organization,
        target=link,
        after={
            "id": str(link.id),
            "vehicle_id": str(vehicle.id),
            "carrier_id": str(carrier.id),
            "link_type": link.link_type,
            "active": link.active,
        },
    )
    return link


@transaction.atomic
def unlink_vehicle_from_carrier(link: CarrierVehicleLink, *, actor=None) -> CarrierVehicleLink:
    before = {
        "id": str(link.id),
        "vehicle_id": str(link.vehicle_id),
        "carrier_id": str(link.carrier_id),
        "link_type": link.link_type,
        "active": link.active,
    }
    link.active = False
    link.full_clean()
    link.save(update_fields=["active", "updated_at"])
    record_audit_event(
        action="vehicle_carrier_unlinked",
        actor=actor,
        organization=link.vehicle.organization,
        target=link,
        before=before,
        after={
            "id": str(link.id),
            "vehicle_id": str(link.vehicle_id),
            "carrier_id": str(link.carrier_id),
            "link_type": link.link_type,
            "active": link.active,
        },
    )
    return link


def _vehicle_audit_payload(vehicle: Vehicle) -> dict[str, Any]:
    return {
        "id": str(vehicle.id),
        "organization_id": str(vehicle.organization_id),
        "plate": vehicle.plate,
        "renavam": "[REDACTED]" if vehicle.renavam else "",
        "chassis": "[REDACTED]" if vehicle.chassis else "",
        "vehicle_type": vehicle.vehicle_type,
        "body_type": vehicle.body_type,
        "cargo_profile": vehicle.cargo_profile,
        "ownership_type": vehicle.ownership_type,
        "brand": vehicle.brand,
        "model": vehicle.model,
        "year": vehicle.year,
        "model_year": vehicle.model_year,
        "state": vehicle.state,
        "status": vehicle.status,
        "operational_status": vehicle.operational_status,
        "capacity_weight_kg": str(vehicle.capacity_weight_kg or ""),
        "gross_weight_kg": str(vehicle.gross_weight_kg or ""),
        "capacity_volume_m3": str(vehicle.capacity_volume_m3 or ""),
        "max_length_m": str(vehicle.max_length_m or ""),
        "max_width_m": str(vehicle.max_width_m or ""),
        "max_height_m": str(vehicle.max_height_m or ""),
        "odometer_km": vehicle.odometer_km,
        "refrigerated": vehicle.refrigerated,
        "closed_box": vehicle.closed_box,
        "open_body": vehicle.open_body,
        "tail_lift": vehicle.tail_lift,
        "helper_available": vehicle.helper_available,
        "hazardous_compatible": vehicle.hazardous_compatible,
    }


def _assignment_audit_payload(assignment: DriverVehicleAssignment) -> dict[str, Any]:
    return {
        "id": str(assignment.id),
        "driver_id": str(assignment.driver_id),
        "vehicle_id": str(assignment.vehicle_id),
        "active": assignment.active,
        "primary": assignment.primary,
        "valid_from": assignment.valid_from.isoformat(),
        "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else "",
    }


def _refrigeration_audit_payload(profile: RefrigerationProfile) -> dict[str, Any]:
    return {
        "vehicle_id": str(profile.vehicle_id),
        "has_refrigeration_unit": profile.has_refrigeration_unit,
        "unit_manufacturer": profile.unit_manufacturer,
        "unit_model": profile.unit_model,
        "temperature_min_c": str(profile.temperature_min_c),
        "temperature_max_c": str(profile.temperature_max_c),
        "default_setpoint_c": str(profile.default_setpoint_c or ""),
        "control_type": profile.control_type,
        "last_maintenance_date": profile.last_maintenance_date.isoformat()
        if profile.last_maintenance_date
        else "",
        "next_maintenance_date": profile.next_maintenance_date.isoformat()
        if profile.next_maintenance_date
        else "",
    }
