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
    OperationSource,
)
from src.carriers.domain.enums import CarrierStatus
from src.freights.domain.state_machine import can_operation_transition
from src.freights.infrastructure.django.models import (
    FreightOperation,
    FreightOperationEvent,
    ProofOfDelivery,
    FreightOfferSelection,
    FreightOfferTarget,
    FreightOperationStop,
    FreightOperationCargoLot,
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
    selection_id: str,
    actor,
    client_event_id: str | None = None,
) -> FreightOperation:
    """Create a FreightOperation from a confirmed FreightOfferSelection.

    Idempotent – if an operation already exists for the selection it is returned.
    Concurrency-safe – the OneToOneField(selection) on FreightOperation acts as
    the natural idempotency key.  Two concurrent calls will either find the
    existing operation via ``select_for_update`` or, in the narrow race window
    between the check and the INSERT, the DB unique constraint on
    ``selection_id`` will raise IntegrityError which is caught and resolved.

    Tenant isolation – the actor must belong to the selection's organization
    (or be a superuser).

    Carrier, driver and vehicle tenant compatibility is validated before
    the operation is created.
    """
    from django.db.utils import IntegrityError
    from src.freights.domain.matching_enums import FreightOfferSelectionStatus

    # 1. Lock the selection row.
    try:
        selection = (
            FreightOfferSelection.objects.select_for_update()
            .select_related("interest")
            .get(id=selection_id)
        )
    except FreightOfferSelection.DoesNotExist:
        raise ValidationError({"selection": "Seleção não encontrada."})

    # 2. Status validation – use domain enum.
    if selection.status != FreightOfferSelectionStatus.CONFIRMED.value:
        raise ValidationError({"selection": "Seleção deve estar confirmada para criar operação."})

    # 3. Tenant isolation – actor must have access to the selection's org.
    if not getattr(actor, "is_superuser", False):
        from src.organizations.infrastructure.django.models import Membership
        actor_has_access = Membership.objects.filter(
            user=actor,
            organization=selection.organization,
            status="ACTIVE",
        ).exists()
        if not actor_has_access:
            raise ValidationError(
                {"selection": "Acesso negado: ator não pertence à organização desta seleção."}
            )

    # 4. Idempotency – if an operation already exists, return it.
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

    # 5. Resolve carrier, driver, vehicle from interest.
    interest = selection.interest
    carrier = interest.carrier
    driver = interest.driver
    vehicle = interest.vehicle
    if not carrier:
        raise ValidationError({"carrier": "Seleção não possui transportadora associada."})
    _ensure_carrier_active(carrier)

    # 6. Tenant compatibility validation for driver and vehicle.
    if driver and driver.organization_id != carrier.tenant_id:
        raise ValidationError(
            {"driver": "Motorista pertence a um tenant diferente da transportadora."}
        )
    if vehicle and vehicle.organization_id != carrier.tenant_id:
        raise ValidationError(
            {"vehicle": "Veículo pertence a um tenant diferente da transportadora."}
        )

    # 7. Create the operation — handle concurrent race via IntegrityError.
    try:
        cargo_min_c = None
        cargo_max_c = None
        try:
            cargo = getattr(selection.offer.freight_request, "cargo", None)
            if cargo:
                cargo_min_c = cargo.temperature_min_c
                cargo_max_c = cargo.temperature_max_c
        except Exception:
            pass

        operation = FreightOperation.objects.create(
            organization=selection.organization,
            selection=selection,
            carrier=carrier,
            driver=driver,
            vehicle=vehicle,
            status=OperationStatus.ASSIGNED.value,
            assigned_at=timezone.now(),
            source_type=OperationSource.MARKETPLACE,
            temperature_min_c=cargo_min_c,
            temperature_max_c=cargo_max_c,
        )
        
        # Copy stops from request to operation
        stops_snapshot = []
        for request_stop in selection.offer.freight_request.stops.all().order_by("sequence", "stop_type"):
            op_stop = FreightOperationStop.objects.create(
                organization=operation.organization,
                operation=operation,
                request_stop=request_stop,
                sequence=request_stop.sequence,
                stop_type=request_stop.stop_type,
                status="PENDING",
                postal_code=request_stop.postal_code,
                street=request_stop.street,
                number=request_stop.number,
                complement=request_stop.complement,
                district=request_stop.district,
                city=request_stop.city,
                state=request_stop.state,
                country=request_stop.country,
                latitude=request_stop.latitude,
                longitude=request_stop.longitude,
                instructions=request_stop.instructions,
                scheduled_date=request_stop.scheduled_date,
                window_start=request_stop.window_start,
                window_end=request_stop.window_end,
            )
            stops_snapshot.append((request_stop.id, op_stop))

        # Copy cargo lots from request to operation
        stop_map = {req_id: op_stop for req_id, op_stop in stops_snapshot}
        for lot in selection.offer.freight_request.cargo_lots.all():
            FreightOperationCargoLot.objects.create(
                operation=operation,
                description=lot.description,
                weight_kg=lot.weight_kg,
                volume_m3=lot.volume_m3,
                package_count=lot.package_count,
                pickup_stop=stop_map[lot.pickup_stop_id],
                delivery_stop=stop_map[lot.delivery_stop_id],
            )
    except IntegrityError:
        # Another concurrent transaction created the operation between our check
        # and this INSERT.  Retrieve it and return idempotently.
        operation = FreightOperation.objects.select_for_update().get(selection=selection)
        return operation

    # 8. Audit log (on_commit – fires only after successful commit).
    record_audit_event(
        action="freight_operation_created",
        actor=actor,
        organization=operation.organization,
        target=operation,
        after={
            "status": operation.status,
            "id": str(operation.id),
            "selection_id": str(selection.id),
        },
    )
    # 9. Create creation event.
    _create_event(
        operation=operation,
        event_type=OperationEventType.OPERATION_CREATED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
        new_status=OperationStatus.ASSIGNED,
        client_event_id=client_event_id,
    )

    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(operation.id),
        event_type="OPERATION_CREATED",
        actor=actor
    ))

    return operation


@transaction.atomic
def change_operation_status(
    *,
    operation_id: str,
    new_status: OperationStatus,
    actor,
    client_event_id: str | None = None,
    driver_only: bool = False,
) -> FreightOperation:
    """Change operation status respecting the state machine and idempotency."""
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)
    current_status = OperationStatus(operation.status)
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

    # Validate transition via state machine
    if not can_operation_transition(current=current_status, target=new_status):
        raise ValidationError({"status": "Transição de status não permitida."})
    # Additional rule: moving to DELIVERED requires an existing POD / all stops completed
    if new_status == OperationStatus.DELIVERED:
        if operation.stops.exists():
            pending_deliveries = operation.stops.filter(
                stop_type="DELIVERY"
            ).exclude(status__in=["COMPLETED", "CANCELLED"])
            if pending_deliveries.exists():
                raise ValidationError({"status": "Operação não pode ser marcada como DELIVERED enquanto houver entregas pendentes."})
            
            completed_deliveries = operation.stops.filter(
                stop_type="DELIVERY", status="COMPLETED"
            )
            for stop in completed_deliveries:
                if not ProofOfDelivery.objects.filter(stop=stop).exists():
                    raise ValidationError({"status": f"A parada de entrega #{stop.sequence} não possui Proof of Delivery registrado."})
        else:
            if not ProofOfDelivery.objects.filter(operation=operation).exists():
                raise ValidationError({"status": "Operação não pode ser marcada como DELIVERED sem Proof of Delivery."})
    operation.status = new_status.value
    operation.save(update_fields=["status", "updated_at"])

    # If transitioning to a terminal state (DELIVERED/CANCELLED), end active tracking sessions
    if new_status in [OperationStatus.DELIVERED, OperationStatus.CANCELLED]:
        from src.freights.domain.enums import TrackingSessionStatus
        from src.freights.infrastructure.django.models import TrackingSession
        active_sessions = TrackingSession.objects.filter(
            operation=operation,
            status=TrackingSessionStatus.ACTIVE.value
        )
        for session in active_sessions:
            session.status = TrackingSessionStatus.ENDED.value
            session.ended_at = timezone.now()
            if session.device_metadata is None:
                session.device_metadata = {}
            reason = "operation_delivered" if new_status == OperationStatus.DELIVERED else "operation_cancelled"
            session.device_metadata["closure_reason"] = reason
            session.save(update_fields=["status", "ended_at", "device_metadata", "updated_at"])
            record_audit_event(
                action="tracking_session_ended",
                actor=actor,
                organization=session.organization,
                target=session,
                before={"status": "ACTIVE"},
                after={
                    "status": session.status,
                    "ended_at": session.ended_at.isoformat(),
                    "closure_reason": reason,
                },
            )

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

    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(operation.id),
        event_type="STATUS_CHANGED",
        actor=actor
    ))

    return operation


@transaction.atomic
def report_operation_incident(
    *,
    operation_id: str,
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

    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(operation.id),
        event_type="INCIDENT_REPORTED",
        actor=actor
    ))

    return event


@transaction.atomic
def cancel_operation(
    *,
    operation_id: str,
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

    # End active tracking sessions upon cancellation
    from src.freights.domain.enums import TrackingSessionStatus
    from src.freights.infrastructure.django.models import TrackingSession
    active_sessions = TrackingSession.objects.filter(
        operation=operation,
        status=TrackingSessionStatus.ACTIVE.value
    )
    for session in active_sessions:
        session.status = TrackingSessionStatus.ENDED.value
        session.ended_at = timezone.now()
        if session.device_metadata is None:
            session.device_metadata = {}
        session.device_metadata["closure_reason"] = "operation_cancelled"
        session.save(update_fields=["status", "ended_at", "device_metadata", "updated_at"])
        record_audit_event(
            action="tracking_session_ended",
            actor=actor,
            organization=session.organization,
            target=session,
            before={"status": "ACTIVE"},
            after={
                "status": session.status,
                "ended_at": session.ended_at.isoformat(),
                "closure_reason": "operation_cancelled",
            },
        )

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
    operation_id: str,
    receiver_name: str,
    delivered_at: timezone.datetime,
    latitude: float | None = None,
    longitude: float | None = None,
    notes: str = "",
    actor,
    driver_only: bool = False,
    stop_id: str | None = None,
) -> ProofOfDelivery:
    """Create ProofOfDelivery linked to operation or specific stop. Only one POD per delivery is allowed."""
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)

    delivery_stops_count = operation.stops.filter(stop_type="DELIVERY").count()
    if delivery_stops_count > 1 and not stop_id:
        raise ValidationError({"stop": "Parada de entrega (stop_id) é obrigatória para operações com múltiplas entregas."})

    stop = None
    if stop_id:
        try:
            stop = operation.stops.get(id=stop_id)
        except FreightOperationStop.DoesNotExist:
            raise ValidationError({"stop": "Parada não encontrada nesta operação."})
        if stop.stop_type != "DELIVERY":
            raise ValidationError({"stop": "Apenas paradas de entrega (DELIVERY) exigem Proof of Delivery."})

    # Idempotency check: if POD already exists for the given context, verify fields.
    try:
        if stop_id:
            existing_pod = ProofOfDelivery.objects.get(stop=stop)
        else:
            existing_pod = ProofOfDelivery.objects.get(operation=operation, stop__isnull=True)
        
        # Safely compare lat/lng
        exist_lat = float(existing_pod.latitude) if existing_pod.latitude is not None else None
        exist_lng = float(existing_pod.longitude) if existing_pod.longitude is not None else None
        new_lat = float(latitude) if latitude is not None else None
        new_lng = float(longitude) if longitude is not None else None

        lat_diff = False
        if (exist_lat is None) != (new_lat is None):
            lat_diff = True
        elif exist_lat is not None and new_lat is not None:
            lat_diff = abs(exist_lat - new_lat) > 1e-6

        lng_diff = False
        if (exist_lng is None) != (new_lng is None):
            lng_diff = True
        elif exist_lng is not None and new_lng is not None:
            lng_diff = abs(exist_lng - new_lng) > 1e-6

        # Compare timestamps safely
        time_diff = False
        if existing_pod.delivered_at and delivered_at:
            time_diff = abs((existing_pod.delivered_at - delivered_at).total_seconds()) > 1.0
        elif existing_pod.delivered_at != delivered_at:
            time_diff = True

        if (
            existing_pod.receiver_name != receiver_name
            or time_diff
            or lat_diff
            or lng_diff
            or existing_pod.notes != notes
        ):
            raise ValidationError({"pod": "Proof of Delivery já registrado com dados diferentes."})
        return existing_pod
    except ProofOfDelivery.DoesNotExist:
        pass

    if stop:
        # For multi-stop operation, stop must be in ARRIVED status
        if stop.status != "ARRIVED":
            raise ValidationError({"status": "Proof of Delivery só pode ser registrado em parada com status ARRIVED."})
    else:
        # Legacy: POD can only be recorded when operation is in UNLOADING state
        if OperationStatus(operation.status) != OperationStatus.UNLOADING:
            raise ValidationError({"status": "Proof of Delivery só pode ser registrado em estado UNLOADING."})

    pod = ProofOfDelivery.objects.create(
        operation=operation,
        stop=stop,
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
        after={"delivered_at": str(delivered_at), "receiver": receiver_name, "stop_id": stop_id},
    )
    _create_event(
        operation=operation,
        event_type=OperationEventType.POD_CREATED,
        actor=actor,
        origin=OperationEventOrigin.SYSTEM,
        metadata={"stop_id": stop_id} if stop_id else None,
    )

    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(operation.id),
        event_type="POD_CREATED",
        actor=actor
    ))

    return pod


@transaction.atomic
def record_thermal_reading(
    *,
    operation_id: str,
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
        min_c = operation.temperature_min_c
        max_c = operation.temperature_max_c
        
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

    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(operation.id),
        event_type="THERMAL_READING_RECORDED",
        actor=actor
    ))

    return reading, False


@transaction.atomic
def assign_carrier_driver_to_operation(
    *,
    actor,
    operation_id,
    driver_id,
) -> FreightOperation:
    """Assign a driver belonging to the carrier to a FreightOperation."""
    from src.identity.domain.enums import PermissionCode
    from src.shared.interfaces.backoffice.authorization import user_has_backoffice_permission, active_memberships_for
    from src.carriers.infrastructure.django.models import CarrierDriverLink
    from src.vehicles.infrastructure.django.models import DriverVehicleAssignment
    from src.drivers.infrastructure.django.models import Driver

    # 1. Fetch operation and check state machine
    try:
        operation = FreightOperation.objects.select_for_update().get(id=operation_id)
    except FreightOperation.DoesNotExist:
        raise ValidationError({"operation": "Operação não encontrada."})

    # Operation in final states cannot have driver reassigned
    if operation.status in [OperationStatus.DELIVERED.value, OperationStatus.CANCELLED.value]:
        raise ValidationError({"operation": "Não é possível alterar motorista em uma operação finalizada."})

    # 2. Check actor permission
    if not user_has_backoffice_permission(actor, PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS.value):
        raise ValidationError({"actor": "Usuário não possui permissão para atualizar operações de frete."})

    # 3. Check actor membership / relationship to the operation's carrier
    carrier = operation.carrier
    if not carrier:
        raise ValidationError({"operation": "Operação não está vinculada a nenhuma transportadora."})

    # Superuser has absolute access
    if not actor.is_superuser:
        memberships = active_memberships_for(actor, PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS.value)
        actor_org_ids = {m.organization_id for m in memberships}
        if carrier.organization_id not in actor_org_ids:
            raise ValidationError({"actor": "Acesso negado: Usuário não pertence à transportadora responsável."})

    # 4. Fetch and validate driver
    try:
        driver = Driver.objects.get(id=driver_id)
    except Driver.DoesNotExist:
        raise ValidationError({"driver": "Motorista não encontrado."})

    if driver.status != "ACTIVE":
        raise ValidationError({"driver": "Motorista deve estar com status ACTIVE."})

    # 5. Check if driver belongs to the same carrier via an active link
    link_exists = CarrierDriverLink.objects.filter(carrier=carrier, driver=driver, active=True).exists()
    if not link_exists:
        raise ValidationError({"driver": "Motorista não está vinculado a esta transportadora."})

    # 6. Check driver tenant / organization compatibility
    if carrier.tenant_id != driver.organization_id:
        raise ValidationError({"driver": "Motorista pertence a um tenant incompatível."})

    # 7. Driver vehicle assignment compatibility
    if operation.vehicle:
        # Check if driver has an active assignment to a different vehicle
        active_assignment = DriverVehicleAssignment.objects.filter(
            driver=driver, active=True
        ).first()
        if active_assignment and active_assignment.vehicle_id != operation.vehicle_id:
            raise ValidationError({"driver": "Motorista possui vínculo incompatível com o veículo da operação."})

    # 8. Record audit log and transition
    before = {
        "driver_id": str(operation.driver_id) if operation.driver_id else None,
        "driver_name": operation.driver.full_name if operation.driver else None,
    }
    after = {
        "driver_id": str(driver.id),
        "driver_name": driver.full_name,
    }

    operation.driver = driver
    operation.save(update_fields=["driver", "updated_at"])

    record_audit_event(
        action="driver_assigned" if before["driver_id"] is None else "driver_reassigned",
        actor=actor,
        organization=operation.organization,
        target=operation,
        before=before,
        after=after,
    )

    return operation


@transaction.atomic
def assign_carrier_vehicle_to_operation(
    *,
    actor,
    operation_id,
    vehicle_id,
) -> FreightOperation:
    """Assign a vehicle belonging to the carrier to a FreightOperation."""
    from src.identity.domain.enums import PermissionCode
    from src.shared.interfaces.backoffice.authorization import user_has_backoffice_permission, active_memberships_for
    from src.carriers.infrastructure.django.models import CarrierVehicleLink
    from src.vehicles.infrastructure.django.models import DriverVehicleAssignment, Vehicle

    # 1. Fetch operation and check state machine
    try:
        operation = FreightOperation.objects.select_for_update().get(id=operation_id)
    except FreightOperation.DoesNotExist:
        raise ValidationError({"operation": "Operação não encontrada."})

    # Operation in final states cannot have vehicle reassigned
    if operation.status in [OperationStatus.DELIVERED.value, OperationStatus.CANCELLED.value]:
        raise ValidationError({"operation": "Não é possível alterar veículo em uma operação finalizada."})

    # 2. Check actor permission
    if not user_has_backoffice_permission(actor, PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS.value):
        raise ValidationError({"actor": "Usuário não possui permissão para atualizar operações de frete."})

    # 3. Check actor membership / relationship to the operation's carrier
    carrier = operation.carrier
    if not carrier:
        raise ValidationError({"operation": "Operação não está vinculada a nenhuma transportadora."})

    # Superuser has absolute access
    if not actor.is_superuser:
        memberships = active_memberships_for(actor, PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS.value)
        actor_org_ids = {m.organization_id for m in memberships}
        if carrier.organization_id not in actor_org_ids:
            raise ValidationError({"actor": "Acesso negado: Usuário não pertence à transportadora responsável."})

    # 4. Fetch and validate vehicle
    try:
        vehicle = Vehicle.objects.get(id=vehicle_id)
    except Vehicle.DoesNotExist:
        raise ValidationError({"vehicle": "Veículo não encontrado."})

    if vehicle.status != "ACTIVE":
        raise ValidationError({"vehicle": "Veículo deve estar com status ACTIVE."})

    # 5. Check if vehicle belongs to the same carrier via an active link
    link_exists = CarrierVehicleLink.objects.filter(carrier=carrier, vehicle=vehicle, active=True).exists()
    if not link_exists:
        raise ValidationError({"vehicle": "Veículo não está vinculado a esta transportadora."})

    # 6. Check vehicle tenant / organization compatibility
    if carrier.tenant_id != vehicle.organization_id:
        raise ValidationError({"vehicle": "Veículo pertence a um tenant incompatível."})

    # 7. Driver vehicle assignment compatibility
    if operation.driver:
        # Check if operation's current driver has an active assignment to a different vehicle
        active_assignment = DriverVehicleAssignment.objects.filter(
            driver=operation.driver, active=True
        ).first()
        if active_assignment and active_assignment.vehicle_id != vehicle.id:
            raise ValidationError({"vehicle": "Veículo é incompatível com o motorista ativo na operação."})

    # 8. Record audit log and transition
    before = {
        "vehicle_id": str(operation.vehicle_id) if operation.vehicle_id else None,
        "vehicle_plate": operation.vehicle.plate if operation.vehicle else None,
    }
    after = {
        "vehicle_id": str(vehicle.id),
        "vehicle_plate": vehicle.plate,
    }

    operation.vehicle = vehicle
    operation.save(update_fields=["vehicle", "updated_at"])

    record_audit_event(
        action="vehicle_assigned" if before["vehicle_id"] is None else "vehicle_reassigned",
        actor=actor,
        organization=operation.organization,
        target=operation,
        before=before,
        after=after,
    )

    return operation


def carrier_operations_visible_to(actor, permission_code: str):
    """Retrieve FreightOperations visible to a carrier user based on their active memberships."""
    from src.shared.interfaces.backoffice.authorization import permission_grant_for
    from src.shared.domain.enums import AccessScope
    from django.db.models import Q

    grant = permission_grant_for(actor, permission_code)
    queryset = FreightOperation.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(selection__offer__owner=actor)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(
        Q(organization_id__in=organization_ids) | Q(carrier__organization_id__in=organization_ids)
    )


@transaction.atomic
def change_stop_status(
    *,
    operation_id: str,
    stop_id: str,
    new_status: str,
    actor,
    driver_only: bool = False,
) -> FreightOperationStop:
    """Transition stop status, enforcing sequence ordering, cargo collection/delivery integrity, and POD rules."""
    operation = _get_operation_for_user(actor, operation_id, driver_only=driver_only)
    
    try:
        stop = operation.stops.select_for_update().get(id=stop_id)
    except FreightOperationStop.DoesNotExist:
        raise ValidationError({"stop": "Parada não encontrada nesta operação."})

    current_status = stop.status
    if current_status == new_status:
        return stop

    # Validate transition: PENDING -> ARRIVED -> COMPLETED
    allowed = False
    if current_status == "PENDING" and new_status in ["ARRIVED", "CANCELLED"]:
        allowed = True
    elif current_status == "ARRIVED" and new_status in ["COMPLETED", "CANCELLED"]:
        allowed = True

    if not allowed:
        raise ValidationError({"status": f"Transição de status de {current_status} para {new_status} não permitida."})

    # Validate sequence order: all previous stops (by sequence) must be COMPLETED or CANCELLED
    previous_stops = operation.stops.filter(sequence__lt=stop.sequence)
    for prev in previous_stops:
        if prev.status not in ["COMPLETED", "CANCELLED"]:
            raise ValidationError({"status": f"A parada anterior #{prev.sequence} deve ser concluída antes da parada #{stop.sequence}."})

    # Cargo integrity check: if delivery stop, all linked cargo lots must have completed pickup stops
    if new_status in ["ARRIVED", "COMPLETED"] and stop.stop_type == "DELIVERY":
        lots = operation.cargo_lots.filter(delivery_stop=stop)
        for lot in lots:
            if lot.pickup_stop.status != "COMPLETED":
                raise ValidationError({"status": f"Não é possível avançar a entrega do lote '{lot.description}' sem antes concluir a coleta correspondente na parada #{lot.pickup_stop.sequence}."})

    # POD check: completing a delivery stop requires a POD recorded
    if new_status == "COMPLETED" and stop.stop_type == "DELIVERY":
        if not ProofOfDelivery.objects.filter(stop=stop).exists():
            raise ValidationError({"status": f"A parada de entrega #{stop.sequence} exige registro de Proof of Delivery."})

    stop.status = new_status
    stop.save(update_fields=["status", "updated_at"])

    # Audit log
    record_audit_event(
        action="freight_operation_stop_status_changed",
        actor=actor,
        organization=operation.organization,
        target=stop,
        before={"status": current_status},
        after={"status": new_status},
    )

    # Event log
    _create_event(
        operation=operation,
        event_type=OperationEventType.STATUS_CHANGED,
        actor=actor,
        origin=OperationEventOrigin.MOBILE_APP if driver_only else OperationEventOrigin.SYSTEM,
        metadata={
            "stop_id": str(stop.id),
            "sequence": stop.sequence,
            "stop_type": stop.stop_type,
            "stop_status": new_status,
        },
    )

    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(operation.id),
        event_type="STATUS_CHANGED",
        actor=actor
    ))

    return stop
