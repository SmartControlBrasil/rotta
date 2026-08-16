from __future__ import annotations
from typing import Any
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.db import transaction

from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import TrackingSessionStatus, OperationStatus
from src.freights.infrastructure.django.models import FreightOperation, TrackingSession, LocationPoint
from src.shared.interfaces.backoffice.authorization import (
    user_has_backoffice_permission,
    scoped_freight_operations_queryset,
)
from src.audit.infrastructure.django.services import record_audit_event


def start_tracking_session(
    actor,
    operation_id: str,
    started_at: Any = None,
    source: str = "",
    device_metadata: dict | None = None,
    client_event_id: str | None = None,
) -> TrackingSession:
    # 1. Permission check
    if not user_has_backoffice_permission(actor, PermissionCode.TRACKING_START):
        raise PermissionDenied("Sem permissão para iniciar rastreamento.")

    # 2. Scope check
    operation_qs = scoped_freight_operations_queryset(actor, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    try:
        operation = operation_qs.get(id=operation_id)
    except FreightOperation.DoesNotExist:
        raise PermissionDenied("Operação não encontrada ou acesso negado.")

    # 3. Valid operation state check
    if operation.status in [OperationStatus.DELIVERED.value, OperationStatus.CANCELLED.value]:
        raise ValidationError(f"Operação no status {operation.status} não aceita rastreamento.")

    started_at = started_at or timezone.now()

    # 4. Prevent ACTIVE duplicate session
    with transaction.atomic():
        active_session = TrackingSession.objects.filter(
            operation=operation,
            status=TrackingSessionStatus.ACTIVE.value
        ).first()

        if active_session:
            return active_session

        # 5. Create tracking session
        session = TrackingSession.objects.create(
            organization=operation.organization,
            operation=operation,
            driver=operation.driver,
            vehicle=operation.vehicle,
            started_at=started_at,
            status=TrackingSessionStatus.ACTIVE.value,
            source=source,
            device_metadata=device_metadata or {},
        )

        # 6. Audit log
        record_audit_event(
            action="tracking_session_started",
            actor=actor,
            organization=operation.organization,
            target=session,
            after={"status": session.status, "id": str(session.id)},
        )

        return session


def record_location_point(
    actor,
    tracking_session_id: str,
    latitude: Any,
    longitude: Any,
    accuracy_m: Any,
    speed_kph: Any = None,
    heading_deg: Any = None,
    altitude_m: Any = None,
    recorded_at: Any = None,
    sequence: int | None = None,
    client_event_id: str | None = None,
    metadata: dict | None = None,
) -> LocationPoint:
    # 1. Permission check
    if not user_has_backoffice_permission(actor, PermissionCode.TRACKING_RECORD):
        raise PermissionDenied("Sem permissão para registrar telemetria.")

    # 2. Get tracking session with scope check
    from src.shared.interfaces.backoffice.authorization import scoped_tracking_sessions_queryset
    session_qs = scoped_tracking_sessions_queryset(actor, PermissionCode.TRACKING_VIEW.value)
    try:
        session = session_qs.get(id=tracking_session_id)
    except TrackingSession.DoesNotExist:
        raise PermissionDenied("Sessão de rastreamento não encontrada ou acesso negado.")

    operation = session.operation

    # 3. Session state check
    if session.status != TrackingSessionStatus.ACTIVE.value:
        raise ValidationError(f"Não é possível registrar pontos em uma sessão {session.status}.")

    # 4. Valid operation state check
    if operation.status in [OperationStatus.DELIVERED.value, OperationStatus.CANCELLED.value]:
        raise ValidationError(f"Não é possível registrar pontos para operação no status {operation.status}.")

    # 5. Geolocation validations
    try:
        lat_dec = Decimal(str(latitude))
        lng_dec = Decimal(str(longitude))
        acc_dec = Decimal(str(accuracy_m))
    except (ValueError, TypeError, ArithmeticError):
        raise ValidationError("Latitude, longitude e precisão devem ser números válidos.")

    if not (-90 <= lat_dec <= 90):
        raise ValidationError("Latitude deve estar entre -90 e 90.")
    if not (-180 <= lng_dec <= 180):
        raise ValidationError("Longitude deve estar entre -180 e 180.")
    if acc_dec < 0:
        raise ValidationError("Precisão (accuracy_m) deve ser maior ou igual a zero.")

    speed_dec = None
    if speed_kph is not None:
        try:
            speed_dec = Decimal(str(speed_kph))
        except (ValueError, TypeError, ArithmeticError):
            raise ValidationError("Velocidade deve ser um número válido.")
        if speed_dec < 0:
            raise ValidationError("Velocidade não pode ser menor que zero.")

    heading_dec = None
    if heading_deg is not None:
        try:
            heading_dec = Decimal(str(heading_deg))
        except (ValueError, TypeError, ArithmeticError):
            raise ValidationError("Direção (heading) deve ser um número válido.")
        if not (0 <= heading_dec < 360):
            raise ValidationError("Direção (heading) deve ser maior ou igual a 0 e menor que 360.")

    alt_dec = None
    if altitude_m is not None:
        try:
            alt_dec = Decimal(str(altitude_m))
        except (ValueError, TypeError, ArithmeticError):
            raise ValidationError("Altitude deve ser um número válido.")

    recorded_at = recorded_at or timezone.now()

    # 6. Idempotency using transaction block and unique database constraints
    with transaction.atomic():
        if client_event_id:
            existing = LocationPoint.objects.filter(
                tracking_session=session,
                client_event_id=client_event_id
            ).first()
            if existing:
                return existing

        if sequence is not None:
            existing = LocationPoint.objects.filter(
                tracking_session=session,
                sequence=sequence
            ).first()
            if existing:
                return existing

        point = LocationPoint.objects.create(
            organization=session.organization,
            tracking_session=session,
            operation=operation,
            driver=session.driver,
            latitude=lat_dec,
            longitude=lng_dec,
            accuracy_m=acc_dec,
            speed_kph=speed_dec,
            heading_deg=heading_dec,
            altitude_m=alt_dec,
            recorded_at=recorded_at,
            sequence=sequence,
            client_event_id=client_event_id,
            metadata=metadata or {},
        )

        return point


def end_tracking_session(
    actor,
    tracking_session_id: str,
    ended_at: Any = None,
) -> TrackingSession:
    # 1. Permission check
    if not user_has_backoffice_permission(actor, PermissionCode.TRACKING_END):
        raise PermissionDenied("Sem permissão para encerrar rastreamento.")

    # 2. Get tracking session with scope check
    from src.shared.interfaces.backoffice.authorization import scoped_tracking_sessions_queryset
    session_qs = scoped_tracking_sessions_queryset(actor, PermissionCode.TRACKING_VIEW.value)
    try:
        session = session_qs.get(id=tracking_session_id)
    except TrackingSession.DoesNotExist:
        raise PermissionDenied("Sessão de rastreamento não encontrada ou acesso negado.")

    # 3. Idempotent check
    if session.status in [TrackingSessionStatus.ENDED.value, TrackingSessionStatus.CANCELLED.value]:
        return session

    ended_at = ended_at or timezone.now()

    with transaction.atomic():
        session.status = TrackingSessionStatus.ENDED.value
        session.ended_at = ended_at
        session.save()

        # Audit log
        record_audit_event(
            action="tracking_session_ended",
            actor=actor,
            organization=session.organization,
            target=session,
            before={"status": "ACTIVE"},
            after={"status": session.status, "ended_at": ended_at.isoformat()},
        )

    return session
