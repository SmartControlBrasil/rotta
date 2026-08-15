from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from src.audit.infrastructure.django.services import record_audit_event
from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus, CarrierVehicleLinkType
from src.carriers.infrastructure.django.models import (
    CarrierDriverLink,
    CarrierProfile,
    CarrierVehicleLink,
)
from src.drivers.infrastructure.django.models import Driver
from src.organizations.infrastructure.django.models import Organization
from src.vehicles.infrastructure.django.models import Vehicle


@dataclass(frozen=True)
class CarrierData:
    tenant: Organization
    organization: Organization
    email: str
    cargo_profile: CarrierCargoProfile = CarrierCargoProfile.DRY_CARGO
    status: CarrierStatus = CarrierStatus.PROSPECT
    owner: Any | None = None
    trade_name: str = ""
    state_registration: str = ""
    municipal_registration: str = ""
    phone: str = ""
    mobile_phone: str = ""
    site: str = ""
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    country: str = "BR"
    rntrc: str = ""
    rntrc_category: str = ""
    rntrc_expiration: date | None = None
    rntrc_status: str = ""


@transaction.atomic
def create_carrier(*, data: CarrierData, actor=None) -> CarrierProfile:
    carrier = CarrierProfile(**data.__dict__)
    carrier.full_clean()
    carrier.save()
    record_audit_event(
        action="carrier_created",
        actor=actor,
        organization=carrier.tenant,
        target=carrier,
        after=_carrier_audit_payload(carrier),
    )
    return carrier


@transaction.atomic
def update_carrier(carrier: CarrierProfile, *, actor=None, **changes) -> CarrierProfile:
    before = _carrier_audit_payload(carrier)
    allowed_fields = {
        "trade_name",
        "state_registration",
        "municipal_registration",
        "email",
        "phone",
        "mobile_phone",
        "site",
        "postal_code",
        "street",
        "number",
        "complement",
        "district",
        "city",
        "state",
        "country",
        "rntrc",
        "rntrc_category",
        "rntrc_expiration",
        "rntrc_status",
        "cargo_profile",
        "owner",
    }
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValidationError({field: "Campo não pode ser atualizado por este caso de uso."})
        setattr(carrier, field, value)
    carrier.full_clean()
    carrier.save()
    record_audit_event(
        action="carrier_updated",
        actor=actor,
        organization=carrier.tenant,
        target=carrier,
        before=before,
        after=_carrier_audit_payload(carrier),
    )
    return carrier


@transaction.atomic
def change_carrier_status(
    carrier: CarrierProfile, *, status: CarrierStatus, actor=None
) -> CarrierProfile:
    before = _carrier_audit_payload(carrier)
    carrier.status = status
    carrier.full_clean()
    carrier.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action="carrier_status_changed",
        actor=actor,
        organization=carrier.tenant,
        target=carrier,
        before=before,
        after=_carrier_audit_payload(carrier),
        metadata={"status": str(status)},
    )
    return carrier


@transaction.atomic
def assign_carrier_owner(
    carrier: CarrierProfile, *, owner: Any | None, actor=None
) -> CarrierProfile:
    before = _carrier_audit_payload(carrier)
    carrier.owner = owner
    carrier.full_clean()
    carrier.save(update_fields=["owner", "updated_at"])
    record_audit_event(
        action="carrier_owner_changed",
        actor=actor,
        organization=carrier.tenant,
        target=carrier,
        before=before,
        after=_carrier_audit_payload(carrier),
        metadata={"owner_id": str(owner.id) if owner else ""},
    )
    return carrier


@transaction.atomic
def link_driver(*, carrier: CarrierProfile, driver: Driver, actor=None) -> CarrierDriverLink:
    link, created = CarrierDriverLink.objects.get_or_create(
        carrier=carrier,
        driver=driver,
        defaults={"active": True},
    )
    if not created and not link.active:
        link.active = True
    link.full_clean()
    link.save()
    record_audit_event(
        action="carrier_driver_linked",
        actor=actor,
        organization=carrier.tenant,
        target=link,
        after=_driver_link_audit_payload(link),
    )
    return link


@transaction.atomic
def unlink_driver(link: CarrierDriverLink, *, actor=None) -> CarrierDriverLink:
    before = _driver_link_audit_payload(link)
    link.active = False
    link.full_clean()
    link.save(update_fields=["active", "updated_at"])
    record_audit_event(
        action="carrier_driver_unlinked",
        actor=actor,
        organization=link.carrier.tenant,
        target=link,
        before=before,
        after=_driver_link_audit_payload(link),
    )
    return link


@transaction.atomic
def link_vehicle(
    *,
    carrier: CarrierProfile,
    vehicle: Vehicle,
    link_type: CarrierVehicleLinkType = CarrierVehicleLinkType.OWNED,
    actor=None,
) -> CarrierVehicleLink:
    link, created = CarrierVehicleLink.objects.get_or_create(
        carrier=carrier,
        vehicle=vehicle,
        defaults={"active": True, "link_type": link_type},
    )
    if not created:
        link.active = True
        link.link_type = link_type
    link.full_clean()
    link.save()
    record_audit_event(
        action="carrier_vehicle_linked",
        actor=actor,
        organization=carrier.tenant,
        target=link,
        after=_vehicle_link_audit_payload(link),
    )
    return link


@transaction.atomic
def unlink_vehicle(link: CarrierVehicleLink, *, actor=None) -> CarrierVehicleLink:
    before = _vehicle_link_audit_payload(link)
    link.active = False
    link.full_clean()
    link.save(update_fields=["active", "updated_at"])
    record_audit_event(
        action="carrier_vehicle_unlinked",
        actor=actor,
        organization=link.carrier.tenant,
        target=link,
        before=before,
        after=_vehicle_link_audit_payload(link),
    )
    return link


def _carrier_audit_payload(carrier: CarrierProfile) -> dict[str, Any]:
    return {
        "id": str(carrier.id),
        "organization_id": str(carrier.organization_id),
        "tenant_id": str(carrier.tenant_id),
        "trade_name": carrier.trade_name,
        "state_registration": carrier.state_registration,
        "municipal_registration": carrier.municipal_registration,
        "email": "[REDACTED]" if carrier.email else "",
        "phone": "[REDACTED]" if carrier.phone else "",
        "mobile_phone": "[REDACTED]" if carrier.mobile_phone else "",
        "rntrc": "[REDACTED]" if carrier.rntrc else "",
        "rntrc_category": carrier.rntrc_category,
        "rntrc_expiration": carrier.rntrc_expiration.isoformat()
        if carrier.rntrc_expiration
        else "",
        "rntrc_status": carrier.rntrc_status,
        "cargo_profile": str(carrier.cargo_profile),
        "status": str(carrier.status),
        "owner_id": str(carrier.owner_id) if carrier.owner_id else "",
    }


def _driver_link_audit_payload(link: CarrierDriverLink) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "carrier_id": str(link.carrier_id),
        "driver_id": str(link.driver_id),
        "active": link.active,
    }


def _vehicle_link_audit_payload(link: CarrierVehicleLink) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "carrier_id": str(link.carrier_id),
        "vehicle_id": str(link.vehicle_id),
        "link_type": str(link.link_type),
        "active": link.active,
    }
