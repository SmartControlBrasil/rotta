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

# Helper to fetch operation with tenant isolation and locking.
def _get_operation_for_user(user, operation_id):
    """Return FreightOperation locked for update if user has access.
    Uses existing RBAC helper to restrict to organizations the user can view.
    """
    from src.shared.interfaces.backoffice.authorization import scoped_organization_queryset
    from src.identity.domain.enums import PermissionCode

    org_qs = scoped_organization_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    try:
        operation = (
            FreightOperation.objects.select_for_update()
            .filter(id=operation_id, organization__in=org_qs)
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
) -> FreightOperation:
    """Change operation status respecting the state machine and idempotency."""
    operation = _get_operation_for_user(actor, operation_id)
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
) -> FreightOperationEvent:
    """Record an incident without changing operation status."""
    operation = _get_operation_for_user(actor, operation_id)
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
) -> ProofOfDelivery:
    """Create ProofOfDelivery linked to operation. Only one POD per operation is allowed."""
    operation = _get_operation_for_user(actor, operation_id)
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
