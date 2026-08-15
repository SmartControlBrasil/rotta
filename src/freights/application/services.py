from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.customers.infrastructure.django.models import Customer
from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightCargoType,
    FreightRequestPriority,
    FreightRequestStatus,
    FreightStopType,
)
from src.freights.domain.state_machine import can_transition
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestCargo,
    FreightRequestReferenceSequence,
    FreightRequestStop,
)
from src.organizations.infrastructure.django.models import Organization


@dataclass(frozen=True)
class StopData:
    stop_type: FreightStopType
    sequence: int = 1
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    country: str = "BR"
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    instructions: str = ""
    scheduled_date: Any | None = None
    window_start: Any | None = None
    window_end: Any | None = None


@dataclass(frozen=True)
class CargoData:
    description: str = ""
    cargo_type: FreightCargoType = FreightCargoType.GENERAL_CARGO
    cargo_profile: FreightCargoProfile = FreightCargoProfile.DRY_CARGO
    quantity: Decimal | None = None
    weight_kg: Decimal | None = None
    volume_m3: Decimal | None = None
    package_count: int | None = None
    package_type: str = ""
    temperature_min_c: Decimal | None = None
    temperature_max_c: Decimal | None = None
    target_temperature_c: Decimal | None = None


@dataclass(frozen=True)
class FreightRequestData:
    organization: Organization
    customer: Customer
    created_by: Any
    owner: Any | None = None
    priority: FreightRequestPriority = FreightRequestPriority.NORMAL
    instructions: str = ""
    handling_requirements: str = ""
    hazardous_material: bool = False
    declared_cargo_value: Decimal | None = None
    currency: str = "BRL"
    vehicle_type_required: str = ""
    body_type_required: str = ""
    stops: tuple[StopData, ...] = ()
    cargo: CargoData | None = None


def _allocate_reference_code(*, organization: Organization) -> str:
    year = timezone.now().year
    sequence, _created = FreightRequestReferenceSequence.objects.select_for_update().get_or_create(
        organization=organization,
        year=year,
        defaults={"last_value": 0},
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value"])
    return f"FR-{year}-{sequence.last_value:06d}"


def _freight_request_audit_payload(freight_request: FreightRequest) -> dict[str, Any]:
    cargo = getattr(freight_request, "cargo", None)
    return {
        "id": str(freight_request.id),
        "reference_code": freight_request.reference_code,
        "status": str(freight_request.status),
        "priority": str(freight_request.priority),
        "customer_id": str(freight_request.customer_id),
        "organization_id": str(freight_request.organization_id),
        "owner_id": str(freight_request.owner_id) if freight_request.owner_id else "",
        "cargo_profile": str(cargo.cargo_profile) if cargo else "",
        "stops_count": freight_request.stops.count(),
    }


def _validate_customer_scope(*, customer: Customer, organization: Organization) -> None:
    if customer.organization_id != organization.id:
        raise ValidationError({"customer": "Cliente deve pertencer à organização informada."})


def _validate_stop_windows(stops: tuple[StopData, ...]) -> None:
    for stop in stops:
        if stop.window_start and stop.window_end and stop.window_end <= stop.window_start:
            raise ValidationError(
                {"window_end": "Fim da janela deve ser posterior ao início da janela."}
            )


def _validate_for_submit(freight_request: FreightRequest) -> None:
    errors: dict[str, str] = {}
    if not freight_request.customer_id:
        errors["customer"] = "Cliente é obrigatório para envio."
    pickup = freight_request.stops.filter(stop_type=FreightStopType.PICKUP.value).first()
    delivery = freight_request.stops.filter(stop_type=FreightStopType.DELIVERY.value).first()
    if not pickup or not pickup.city or not pickup.state:
        errors["pickup"] = "Origem com cidade e UF é obrigatória para envio."
    if not delivery or not delivery.city or not delivery.state:
        errors["delivery"] = "Destino com cidade e UF é obrigatório para envio."
    try:
        cargo = freight_request.cargo
    except FreightRequestCargo.DoesNotExist:
        cargo = None
    if not cargo:
        errors["cargo"] = "Descrição da carga é obrigatória para envio."
    else:
        if not cargo.cargo_profile:
            errors["cargo_profile"] = "Perfil da carga é obrigatório."
        if cargo.weight_kg is None and cargo.volume_m3 is None:
            errors["weight_kg"] = "Informe peso ou volume para envio."
        if cargo.cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
            if cargo.temperature_min_c is None or cargo.temperature_max_c is None:
                errors["temperature_min_c"] = "Carga refrigerada exige faixa térmica."
            else:
                try:
                    cargo.full_clean()
                except ValidationError as exc:
                    errors.update(
                        {
                            key: value[0] if isinstance(value, list) else value
                            for key, value in exc.message_dict.items()
                        }
                    )
        else:
            try:
                cargo.full_clean()
            except ValidationError as exc:
                errors.update(
                    {
                        key: value[0] if isinstance(value, list) else value
                        for key, value in exc.message_dict.items()
                    }
                )
    if errors:
        raise ValidationError(errors)


def _sync_stops(freight_request: FreightRequest, stops: tuple[StopData, ...]) -> None:
    freight_request.stops.all().delete()
    for stop in stops:
        instance = FreightRequestStop(
            freight_request=freight_request,
            sequence=stop.sequence,
            stop_type=stop.stop_type.value,
            postal_code=stop.postal_code,
            street=stop.street,
            number=stop.number,
            complement=stop.complement,
            district=stop.district,
            city=stop.city,
            state=stop.state.upper() if stop.state else "",
            country=stop.country or "BR",
            latitude=stop.latitude,
            longitude=stop.longitude,
            instructions=stop.instructions,
            scheduled_date=stop.scheduled_date,
            window_start=stop.window_start,
            window_end=stop.window_end,
        )
        instance.full_clean()
        instance.save()


def _sync_cargo(freight_request: FreightRequest, cargo_data: CargoData | None) -> None:
    if cargo_data is None:
        return
    cargo, _created = FreightRequestCargo.objects.get_or_create(freight_request=freight_request)
    cargo.description = cargo_data.description
    cargo.cargo_type = cargo_data.cargo_type.value
    cargo.cargo_profile = cargo_data.cargo_profile.value
    cargo.quantity = cargo_data.quantity
    cargo.weight_kg = cargo_data.weight_kg
    cargo.volume_m3 = cargo_data.volume_m3
    cargo.package_count = cargo_data.package_count
    cargo.package_type = cargo_data.package_type
    cargo.temperature_min_c = cargo_data.temperature_min_c
    cargo.temperature_max_c = cargo_data.temperature_max_c
    cargo.target_temperature_c = cargo_data.target_temperature_c
    cargo.full_clean()
    cargo.save()


@transaction.atomic
def create_freight_request(*, data: FreightRequestData, actor=None) -> FreightRequest:
    _validate_customer_scope(customer=data.customer, organization=data.organization)
    _validate_stop_windows(data.stops)
    reference_code = _allocate_reference_code(organization=data.organization)
    freight_request = FreightRequest(
        organization=data.organization,
        customer=data.customer,
        created_by=data.created_by,
        owner=data.owner or data.created_by,
        reference_code=reference_code,
        status=FreightRequestStatus.DRAFT.value,
        priority=data.priority.value,
        instructions=data.instructions,
        handling_requirements=data.handling_requirements,
        hazardous_material=data.hazardous_material,
        declared_cargo_value=data.declared_cargo_value,
        currency=data.currency or "BRL",
        vehicle_type_required=data.vehicle_type_required,
        body_type_required=data.body_type_required,
    )
    freight_request.full_clean()
    freight_request.save()
    if data.stops:
        _sync_stops(freight_request, data.stops)
    if data.cargo:
        _sync_cargo(freight_request, data.cargo)
    record_audit_event(
        action="freight_request_created",
        actor=actor,
        organization=freight_request.organization,
        target=freight_request,
        after=_freight_request_audit_payload(freight_request),
    )
    return freight_request


@transaction.atomic
def update_freight_request(
    freight_request: FreightRequest,
    *,
    actor=None,
    **changes,
) -> FreightRequest:
    if freight_request.status != FreightRequestStatus.DRAFT.value:
        raise ValidationError({"status": "Somente rascunhos podem ser editados."})
    before = _freight_request_audit_payload(freight_request)
    allowed_fields = {
        "customer",
        "owner",
        "priority",
        "instructions",
        "handling_requirements",
        "hazardous_material",
        "declared_cargo_value",
        "currency",
        "vehicle_type_required",
        "body_type_required",
    }
    stops = changes.pop("stops", None)
    cargo = changes.pop("cargo", None)
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValidationError({field: "Campo não pode ser atualizado por este caso de uso."})
        if field == "customer":
            _validate_customer_scope(customer=value, organization=freight_request.organization)
        if field == "priority" and isinstance(value, FreightRequestPriority):
            value = value.value
        setattr(freight_request, field, value)
    freight_request.full_clean()
    freight_request.save()
    if stops is not None:
        _validate_stop_windows(stops)
        _sync_stops(freight_request, stops)
    if cargo is not None:
        _sync_cargo(freight_request, cargo)
    record_audit_event(
        action="freight_request_updated",
        actor=actor,
        organization=freight_request.organization,
        target=freight_request,
        before=before,
        after=_freight_request_audit_payload(freight_request),
    )
    return freight_request


@transaction.atomic
def submit_freight_request(freight_request: FreightRequest, *, actor=None) -> FreightRequest:
    before = _freight_request_audit_payload(freight_request)
    current = FreightRequestStatus(freight_request.status)
    target = FreightRequestStatus.SUBMITTED
    if not can_transition(current=current, target=target):
        raise ValidationError({"status": "Transição de status não permitida."})
    _validate_for_submit(freight_request)
    freight_request.status = target.value
    freight_request.submitted_at = timezone.now()
    freight_request.full_clean()
    freight_request.save(update_fields=["status", "submitted_at", "updated_at"])
    record_audit_event(
        action="freight_request_submitted",
        actor=actor,
        organization=freight_request.organization,
        target=freight_request,
        before=before,
        after=_freight_request_audit_payload(freight_request),
    )
    return freight_request


@transaction.atomic
def change_freight_request_status(
    freight_request: FreightRequest,
    *,
    status: FreightRequestStatus,
    actor=None,
) -> FreightRequest:
    before = _freight_request_audit_payload(freight_request)
    current = FreightRequestStatus(freight_request.status)
    if not can_transition(current=current, target=status):
        raise ValidationError({"status": "Transição de status não permitida."})
    freight_request.status = status.value
    freight_request.full_clean()
    freight_request.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action="freight_request_status_changed",
        actor=actor,
        organization=freight_request.organization,
        target=freight_request,
        before=before,
        after=_freight_request_audit_payload(freight_request),
        metadata={"status": str(status)},
    )
    return freight_request


@transaction.atomic
def cancel_freight_request(
    freight_request: FreightRequest,
    *,
    reason: str,
    actor=None,
) -> FreightRequest:
    if not reason.strip():
        raise ValidationError({"cancellation_reason": "Motivo de cancelamento é obrigatório."})
    before = _freight_request_audit_payload(freight_request)
    current = FreightRequestStatus(freight_request.status)
    target = FreightRequestStatus.CANCELLED
    if not can_transition(current=current, target=target):
        raise ValidationError({"status": "Transição de status não permitida."})
    freight_request.status = target.value
    freight_request.cancelled_at = timezone.now()
    freight_request.cancelled_by = actor
    freight_request.cancellation_reason = reason.strip()
    freight_request.full_clean()
    freight_request.save(
        update_fields=[
            "status",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "updated_at",
        ]
    )
    record_audit_event(
        action="freight_request_cancelled",
        actor=actor,
        organization=freight_request.organization,
        target=freight_request,
        before=before,
        after=_freight_request_audit_payload(freight_request),
        metadata={"reason": reason.strip()},
    )
    return freight_request


@transaction.atomic
def assign_freight_request_owner(
    freight_request: FreightRequest,
    *,
    owner: Any,
    actor=None,
) -> FreightRequest:
    before = _freight_request_audit_payload(freight_request)
    freight_request.owner = owner
    freight_request.full_clean()
    freight_request.save(update_fields=["owner", "updated_at"])
    record_audit_event(
        action="freight_request_owner_changed",
        actor=actor,
        organization=freight_request.organization,
        target=freight_request,
        before=before,
        after=_freight_request_audit_payload(freight_request),
        metadata={"owner_id": str(owner.id) if owner else ""},
    )
    return freight_request
