# src/freights/application/operation_services.py
"""Freight operation service layer.
Implements creation, status changes, incident reporting, cancellation and POD recording.
All functions are transactional, use select_for_update for concurrency safety,
enforce carrier ACTIVE status, idempotency via client_event_id and audit logging.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from src.audit.infrastructure.django.services import record_audit_event
from src.freights.domain.enums import (
    OperationStatus,
    OperationEventType,
    OperationEventOrigin,
)
from src.carriers.domain.enums import CarrierStatus
from src.freights.domain.state_machine import can_operation_transition
from src.freights.infrastructure.django.models import (
    FreightOperation,
    FreightOperationEvent,
    ProofOfDelivery,
    FreightOfferSelection,
    FreightOfferTarget,
)
from src.carriers.infrastructure.django.models import CarrierProfile

def _get_operation_for_user(user, operation_id, *, driver_only: bool = False):
    """Return FreightOperation locked for update if user has access.
    Uses existing RBAC helper to restrict to organizations the user can view,
    or permits direct access if the user is the driver assigned to the operation.
    If driver_only is true, it strictly limits the search to the user's driver profiles.
    """
    from django.db.models import Q
    from src.shared.interfaces.backoffice.authorization import scoped_organization_queryset
    from src.identity.domain.enums import PermissionCode

    if driver_only:
        if not hasattr(user, "driver_profiles"):
            raise ValidationError({"operation": "Usuário não possui perfil de motorista."})
        driver_ids = list(user.driver_profiles.values_list("id", flat=True))
        try:
            return (
                FreightOperation.objects.select_for_update()
                .filter(driver_id__in=driver_ids, id=operation_id)
                .get()
            )
        except FreightOperation.DoesNotExist:
            raise ValidationError({"operation": "Operação não encontrada ou sem permissão."})

    org_qs = scoped_organization_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    
    driver_ids = []
    if hasattr(user, "driver_profiles"):
        driver_ids = list(user.driver_profiles.values_list("id", flat=True))

    try:
        operation = (
            FreightOperation.objects.select_for_update()
            .filter(
                Q(organization__in=org_qs) | Q(driver_id__in=driver_ids),
                id=operation_id,
            )
            .get()
        )
    except FreightOperation.DoesNotExist:
        raise ValidationError({"operation": "Operação não encontrada ou sem permissão."})
    return operation




def _ensure_carrier_active(carrier: CarrierProfile) -> None:
    """Validate carrier status is ACTIVE."""
    if carrier.status != CarrierStatus.ACTIVE.value:
        raise ValidationError({"carrier": "Transportadora deve estar com status ACTIVE."})


def _create_event(
    *,
    operation: FreightOperation,
    event_type: OperationEventType,
    actor,
    origin: OperationEventOrigin = OperationEventOrigin.SYSTEM,
    previous_status: OperationStatus | None = None,
    new_status: OperationStatus | None = None,
    client_event_id: str | None = None,
    metadata: dict | None = None,
) -> FreightOperationEvent:
    """Create a FreightOperationEvent respecting idempotency.
    If client_event_id is provided and an event with the same identifier exists
    for the operation, the existing event is returned.
    """
    if client_event_id:
        existing = FreightOperationEvent.objects.filter(
            operation=operation,
            client_event_id=client_event_id,
        ).first()
        if existing:
            return existing
    event = FreightOperationEvent.objects.create(
        operation=operation,
        event_type=event_type.value,
        previous_status=previous_status.value if previous_status else None,
        new_status=new_status.value if new_status else None,
        actor=actor,
        origin=origin.value,
        occurred_at=timezone.now(),
        client_event_id=client_event_id,
        metadata=metadata or {},
    )
    return event


@transaction.atomic
def create_operation_from_selection(
    *,
    selection_id: int,
    actor,
    client_event_id: str | None = None,
) -> FreightOperation:
    """Create a FreightOperation from a confirmed FreightOfferSelection.
    Idempotent – if an operation already exists for the selection it is returned.
    """
    try:
        selection = (
            FreightOfferSelection.objects.select_for_update()
            .get(id=selection_id)
        )
    except FreightOfferSelection.DoesNotExist:
        raise ValidationError({"selection": "Seleção não encontrada."})

    if selection.status != "CONFIRMED":
        raise ValidationError({"selection": "Seleção deve estar confirmada para criar operação."})

    # Idempotency – attempt to lock existing operation if any.
    try:
        existing_op = (
            FreightOperation.objects.select_for_update()
            .get(selection=selection)
        )
    except FreightOperation.DoesNotExist:
        existing_op = None
    if existing_op:
        if client_event_id:
            _create_event(
                operation=existing_op,
                event_type=OperationEventType.OPERATION_CREATED,
                actor=actor,
                origin=OperationEventOrigin.SYSTEM,
                client_event_id=client_event_id,
            )
        return existing_op

    # Determine carrier, driver, vehicle from the confirmed interest.
    interest = selection.interest
    carrier = interest.carrier
    driver = interest.driver
    vehicle = interest.vehicle
    if not carrier:
        raise ValidationError({"carrier": "Seleção não possui transportadora associada."})
    _ensure_carrier_active(carrier)

    operation = FreightOperation.objects.create(
        organization=selection.organization,
        selection=selection,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status=OperationStatus.ASSIGNED.value,
        assigned_at=timezone.now(),
    )
    # Audit log
    record_audit_event(
        action="freight_operation_created",
        actor=actor,
        organization=operation.organization,
        target=operation,
        after={"status": operation.status, "id": str(operation.id)},
    )
    # Create creation event
    _create_event(
        operation=operation,
        event_type=OperationEventType.OPERATION_CREATED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
        new_status=OperationStatus.ASSIGNED,
        client_event_id=client_event_id,
    )
    return operation


@transaction.atomic
def change_operation_status(
    *,
    operation_id: int,
    new_status: OperationStatus,
    actor,
    client_event_id: str | None = None,
    driver_only: bool = False,
) -> FreightOperation:
    """Change operation status respecting the state machine and idempotency."""
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)
    current_status = OperationStatus(operation.status)
    # Validate transition via state machine
    if not can_operation_transition(current=current_status, target=new_status):
        raise ValidationError({"status": "Transição de status não permitida."})
    # Additional rule: moving to DELIVERED requires an existing POD
    if new_status == OperationStatus.DELIVERED:
        if not ProofOfDelivery.objects.filter(operation=operation).exists():
            raise ValidationError({"status": "Operação não pode ser marcada como DELIVERED sem Proof of Delivery."})
    if current_status == new_status:
        if client_event_id:
            _create_event(
                operation=operation,
                event_type=OperationEventType.STATUS_CHANGED,
                actor=actor,
                origin=OperationEventOrigin.SYSTEM,
                previous_status=current_status,
                new_status=new_status,
                client_event_id=client_event_id,
            )
        return operation
    operation.status = new_status.value
    operation.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action="freight_operation_status_changed",
        actor=actor,
        organization=operation.organization,
        target=operation,
        before={"status": current_status.value},
        after={"status": new_status.value},
    )
    _create_event(
        operation=operation,
        event_type=OperationEventType.STATUS_CHANGED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
        previous_status=current_status,
        new_status=new_status,
        client_event_id=client_event_id,
    )
    return operation


@transaction.atomic
def report_operation_incident(
    *,
    operation_id: int,
    description: str,
    actor,
    client_event_id: str | None = None,
    driver_only: bool = False,
) -> FreightOperationEvent:
    """Record an incident without changing operation status."""
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)
    event = _create_event(
        operation=operation,
        event_type=OperationEventType.INCIDENT_REPORTED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
        client_event_id=client_event_id,
        metadata={"description": description},
    )
    record_audit_event(
        action="freight_operation_incident_reported",
        actor=actor,
        organization=operation.organization,
        target=operation,
        after={"incident": description},
    )
    return event


@transaction.atomic
def cancel_operation(
    *,
    operation_id: int,
    reason: str,
    actor,
    client_event_id: str | None = None,
) -> FreightOperation:
    """Cancel the operation, transitioning to CANCELLED status."""
    operation = _get_operation_for_user(actor, operation_id)
    current_status = OperationStatus(operation.status)
    target_status = OperationStatus.CANCELLED
    if not can_operation_transition(current=current_status, target=target_status):
        raise ValidationError({"status": "Transição de cancelamento não permitida."})
    operation.status = target_status.value
    operation.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action="freight_operation_cancelled",
        actor=actor,
        organization=operation.organization,
        target=operation,
        before={"status": current_status.value},
        after={"status": target_status.value, "reason": reason},
    )
    _create_event(
        operation=operation,
        event_type=OperationEventType.CANCELLED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
        previous_status=current_status,
        new_status=target_status,
        client_event_id=client_event_id,
        metadata={"reason": reason},
    )
    return operation


@transaction.atomic
def record_proof_of_delivery(
    *,
    operation_id: int,
    receiver_name: str,
    delivered_at: timezone.datetime,
    latitude: float | None = None,
    longitude: float | None = None,
    notes: str = "",
    actor,
    driver_only: bool = False,
) -> ProofOfDelivery:
    """Create ProofOfDelivery linked to operation. Only one POD per operation is allowed."""
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)
    # POD can only be recorded when operation is in UNLOADING state
    if OperationStatus(operation.status) != OperationStatus.UNLOADING:
        raise ValidationError({"status": "Proof of Delivery só pode ser registrado em estado UNLOADING."})
    if ProofOfDelivery.objects.filter(operation=operation).exists():
        raise ValidationError({"pod": "Proof of Delivery já registrado para esta operação."})
    pod = ProofOfDelivery.objects.create(
        operation=operation,
        receiver_name=receiver_name,
        delivered_at=delivered_at,
        latitude=latitude,
        longitude=longitude,
        notes=notes,
    )
    record_audit_event(
        action="proof_of_delivery_created",
        actor=actor,
        organization=operation.organization,
        target=pod,
        after={"delivered_at": str(delivered_at), "receiver": receiver_name},
    )
    _create_event(
        operation=operation,
        event_type=OperationEventType.POD_CREATED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
    )
    return pod


@transaction.atomic
def record_thermal_reading(
    *,
    operation_id: int,
    device_id: str,
    sensor_timestamp: timezone.datetime,
    temperature_c: Decimal,
    quality: str = "VALID",
    validity: str = "VALID",
    client_event_id: str | None = None,
    metadata: dict | None = None,
    actor,
    driver_only: bool = False,
) -> tuple[ThermalReading, bool]:
    """Record a thermal reading for a freight operation.
    Idempotent – returns existing reading and True if duplicate.
    Detects and manages ThermalExcursions based on cargo limits.
    """
    from decimal import Decimal
    from src.freights.infrastructure.django.models import ThermalReading, ThermalExcursion
    from src.freights.domain.enums import (
        ThermalReadingQuality,
        ThermalReadingValidity,
        ThermalExcursionStatus,
        ThermalExcursionDirection,
    )
    
    # 1. Validate operation and driver access
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)
    
    # 2. Idempotency checks
    if client_event_id:
        existing = ThermalReading.objects.filter(
            operation=operation,
            client_event_id=client_event_id
        ).first()
        if existing:
            return existing, True

    existing_ts = ThermalReading.objects.filter(
        operation=operation,
        device_id=device_id,
        sensor_timestamp=sensor_timestamp
    ).first()
    if existing_ts:
        return existing_ts, True

    # 3. Validate timestamp
    now = timezone.now()
    if sensor_timestamp > now + timezone.timedelta(minutes=5):
        raise ValidationError({"sensor_timestamp": "Timestamp no futuro não é permitido."})

    # Normalise quality/validity
    val_enum = ThermalReadingValidity.VALID
    if validity in [item.value for item in ThermalReadingValidity]:
        val_enum = ThermalReadingValidity(validity)
    
    if sensor_timestamp < now - timezone.timedelta(hours=24):
        val_enum = ThermalReadingValidity.STALE

    qual_enum = ThermalReadingQuality.VALID
    if quality in [item.value for item in ThermalReadingQuality]:
        qual_enum = ThermalReadingQuality(quality)

    # 4. Save reading
    reading = ThermalReading.objects.create(
        operation=operation,
        device_id=device_id,
        sensor_timestamp=sensor_timestamp,
        temperature_c=temperature_c,
        quality=qual_enum.value,
        validity=val_enum.value,
        client_event_id=client_event_id,
        metadata=metadata or {},
        vehicle=operation.vehicle,
    )

    # 5. Evaluate Thermal Excursion
    # Only calculate if reading is VALID
    if val_enum == ThermalReadingValidity.VALID:
        cargo = None
        try:
            offer = operation.selection.offer
            if offer and offer.freight_request:
                cargo = getattr(offer.freight_request, 'cargo', None)
        except Exception:
            pass

        if cargo:
            min_c = cargo.temperature_min_c
            max_c = cargo.temperature_max_c
            
            if min_c is not None or max_c is not None:
                temp = Decimal(str(temperature_c))
                is_below = (min_c is not None and temp < min_c)
                is_above = (max_c is not None and temp > max_c)
                
                # Fetch active excursion for this operation and device
                active_excursion = ThermalExcursion.objects.select_for_update().filter(
                    operation=operation,
                    sensor_id=device_id,
                    status=ThermalExcursionStatus.ACTIVE.value
                ).first()

                if is_below or is_above:
                    direction = ThermalExcursionDirection.BELOW_MIN if is_below else ThermalExcursionDirection.ABOVE_MAX
                    
                    if active_excursion:
                        if active_excursion.direction == direction.value:
                            # Update bounds
                            active_excursion.min_observed = min(active_excursion.min_observed, temp)
                            active_excursion.max_observed = max(active_excursion.max_observed, temp)
                            active_excursion.save(update_fields=["min_observed", "max_observed", "updated_at"])
                        else:
                            # Direction changed! Resolve current active and open a new one
                            active_excursion.status = ThermalExcursionStatus.RESOLVED.value
                            active_excursion.ended_at = sensor_timestamp
                            active_excursion.save(update_fields=["status", "ended_at", "updated_at"])
                            
                            ThermalExcursion.objects.create(
                                operation=operation,
                                sensor_id=device_id,
                                started_at=sensor_timestamp,
                                direction=direction.value,
                                min_observed=temp,
                                max_observed=temp,
                                status=ThermalExcursionStatus.ACTIVE.value
                            )
                    else:
                        # Create new excursion
                        ThermalExcursion.objects.create(
                            operation=operation,
                            sensor_id=device_id,
                            started_at=sensor_timestamp,
                            direction=direction.value,
                            min_observed=temp,
                            max_observed=temp,
                            status=ThermalExcursionStatus.ACTIVE.value
                        )
                else:
                    # Within bounds! Resolve active excursion if any
                    if active_excursion:
                        active_excursion.status = ThermalExcursionStatus.RESOLVED.value
                        active_excursion.ended_at = sensor_timestamp
                        active_excursion.save(update_fields=["status", "ended_at", "updated_at"])

    return reading, False
