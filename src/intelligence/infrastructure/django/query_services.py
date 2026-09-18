from django.core.exceptions import PermissionDenied, ValidationError
from src.intelligence.application.ports import OperationContextPort, OperationResultContextPort
from src.intelligence.domain.models import (
    OperationContext,
    CarrierContext,
    DriverContext,
    VehicleContext,
    StopContext,
    CargoLotContext,
    SLAContext,
    TrackingContext,
    IncidentContext,
    ThermalContext,
    EventContext,
    OperationResultContext,
)

class DjangoOperationContextQueryService(OperationContextPort):
    """Retrieves operational data from the Django database and builds the OperationContext DTO.

    Enforces strict tenant isolation checks.
    """

    def get_context(self, operation_id: str, actor) -> OperationContext:
        from src.freights.infrastructure.django.models import FreightOperation

        # 1. Fetch FreightOperation
        try:
            operation = (
                FreightOperation.objects
                .select_related("organization", "carrier", "driver__user", "vehicle")
                .prefetch_related("stops", "cargo_lots", "tracking_sessions", "location_points", "thermal_readings", "thermal_excursions", "events__actor")
                .get(id=operation_id)
            )
        except (FreightOperation.DoesNotExist, ValidationError):
            raise ValueError("Operação não encontrada.")

        # 2. Tenant isolation check
        if not getattr(actor, "is_superuser", False):
            from src.organizations.infrastructure.django.models import Membership
            has_access = Membership.objects.filter(
                user=actor,
                organization=operation.organization,
                status="ACTIVE"
            ).exists()
            if not has_access:
                raise PermissionDenied("Acesso negado: ator não pertence à organização desta operação.")

        # 3. Map Carrier
        carrier_ctx = None
        if operation.carrier:
            carrier_ctx = CarrierContext(
                id=str(operation.carrier.id),
                trade_name=operation.carrier.trade_name,
                status=operation.carrier.status,
            )

        # 4. Map Driver
        driver_ctx = None
        if operation.driver:
            driver_ctx = DriverContext(
                id=str(operation.driver.id),
                full_name=operation.driver.full_name,
                email=getattr(operation.driver.user, "email", ""),
            )

        # 5. Map Vehicle
        vehicle_ctx = None
        if operation.vehicle:
            vehicle_ctx = VehicleContext(
                id=str(operation.vehicle.id),
                plate=operation.vehicle.plate,
                vehicle_type=operation.vehicle.vehicle_type,
            )

        # 6. Map Stops
        stop_ctxs = []
        for stop in operation.stops.all().order_by("sequence"):
            stop_ctxs.append(
                StopContext(
                    id=str(stop.id),
                    sequence=stop.sequence,
                    stop_type=stop.stop_type,
                    status=stop.status,
                    scheduled_date=stop.scheduled_date,
                    window_start=stop.window_start,
                    window_end=stop.window_end,
                    city=stop.city,
                    state=stop.state,
                    latitude=float(stop.latitude) if stop.latitude is not None else None,
                    longitude=float(stop.longitude) if stop.longitude is not None else None,
                    arrived_at=None,
                    completed_at=None,
                )
            )

        # 7. Map Cargo Lots
        cargo_lot_ctxs = []
        for lot in operation.cargo_lots.all():
            cargo_lot_ctxs.append(
                CargoLotContext(
                    id=str(lot.id),
                    description=lot.description,
                    weight_kg=float(lot.weight_kg) if lot.weight_kg is not None else 0.0,
                    volume_m3=float(lot.volume_m3) if lot.volume_m3 is not None else 0.0,
                    pickup_stop_id=str(lot.pickup_stop_id),
                    delivery_stop_id=str(lot.delivery_stop_id),
                )
            )

        # 8. Map SLA
        from src.freights.application.sla_service import SLAService
        sla_res = SLAService.compute(operation)
        sla_ctx = SLAContext(
            status=sla_res.state.value,
            planned_deadline=sla_res.planned_deadline,
            delay_minutes=sla_res.computed_delay_minutes or 0,
        )

        # 9. Map Tracking
        active_session_exists = operation.tracking_sessions.filter(status="ACTIVE").exists()
        last_point = operation.location_points.order_by("-recorded_at").first()
        tracking_ctx = TrackingContext(
            has_active_session=active_session_exists,
            last_latitude=float(last_point.latitude) if last_point else None,
            last_longitude=float(last_point.longitude) if last_point else None,
            last_timestamp=last_point.recorded_at if last_point else None,
            total_points=operation.location_points.count(),
        )

        # 10. Map Incidents (Operational events with type icontains "INCIDENT")
        incident_ctxs = []
        for evt in operation.events.filter(event_type__icontains="INCIDENT").order_by("occurred_at"):
            desc = None
            if evt.metadata and isinstance(evt.metadata, dict):
                desc = evt.metadata.get("description")
            incident_ctxs.append(
                IncidentContext(
                    id=str(evt.id),
                    event_type=evt.event_type,
                    occurred_at=evt.occurred_at,
                    description=desc,
                )
            )

        # 11. Map Thermal Telemetry
        last_reading = operation.thermal_readings.order_by("-sensor_timestamp").first()
        is_currently_in_excursion = operation.thermal_excursions.filter(ended_at__isnull=True).exists()
        thermal_ctx = ThermalContext(
            temperature_min_c=float(operation.temperature_min_c) if operation.temperature_min_c is not None else None,
            temperature_max_c=float(operation.temperature_max_c) if operation.temperature_max_c is not None else None,
            last_reading=float(last_reading.temperature_c) if last_reading else None,
            last_reading_at=last_reading.sensor_timestamp if last_reading else None,
            excursion_count=operation.thermal_excursions.count(),
            is_in_excursion=is_currently_in_excursion,
        )

        # 12. Map General Timeline Events
        event_ctxs = []
        for evt in operation.events.all().order_by("occurred_at"):
            event_ctxs.append(
                EventContext(
                    id=str(evt.id),
                    event_type=evt.event_type,
                    occurred_at=evt.occurred_at,
                    actor_username=evt.actor.username if evt.actor else None,
                )
            )

        return OperationContext(
            operation_id=str(operation.id),
            organization_id=str(operation.organization_id),
            status=operation.status,
            source_type=operation.source_type,
            carrier=carrier_ctx,
            driver=driver_ctx,
            vehicle=vehicle_ctx,
            stops=stop_ctxs,
            cargo_lots=cargo_lot_ctxs,
            sla=sla_ctx,
            tracking=tracking_ctx,
            incidents=incident_ctxs,
            thermal=thermal_ctx,
            events=event_ctxs,
        )


class DjangoOperationResultContextQueryService(OperationResultContextPort):
    """Loads operational result/outcome context from Django ORM, enforcing tenant isolation."""

    def get_result_context(self, operation_id: str, actor) -> OperationResultContext:
        from src.freights.infrastructure.django.models import FreightOperation, FreightOperationStop
        from src.organizations.infrastructure.django.models import Membership
        from django.core.exceptions import PermissionDenied, ValidationError

        try:
            operation = FreightOperation.objects.select_related("organization").prefetch_related(
                "stops",
                "thermal_excursions",
                "events",
                "pods"
            ).get(id=operation_id)
        except (FreightOperation.DoesNotExist, ValidationError):
            raise ValueError("Operação não encontrada.")

        # Multi-tenant check
        if not getattr(actor, "is_superuser", False):
            membership_exists = Membership.objects.filter(
                user=actor,
                organization=operation.organization,
                status="ACTIVE"
            ).exists()
            if not membership_exists:
                raise PermissionDenied("Acesso negado: ator não pertence à organização desta operação.")

        # Resolve SLA details
        from src.freights.application.sla_service import SLAService
        sla_result = SLAService.compute(operation)
        planned_deadline = sla_result.planned_deadline

        # Resolve stops completion & PODs
        delivery_stops = [s for s in operation.stops.all() if s.stop_type == "DELIVERY"]
        all_delivery_completed = len(delivery_stops) > 0 and all(s.status == "COMPLETED" for s in delivery_stops)

        # Check pods
        pods = list(operation.pods.all())
        pod_stop_ids = {str(p.stop_id) for p in pods if p.stop_id is not None}
        all_delivery_have_pod = len(delivery_stops) > 0 and all(str(s.id) in pod_stop_ids for s in delivery_stops)

        # Excursion count
        excursion_count = operation.thermal_excursions.count()
        has_thermal_requirement = operation.temperature_min_c is not None or operation.temperature_max_c is not None

        # Incident count
        incident_events = [e for e in operation.events.all() if "INCIDENT" in e.event_type.upper()]
        total_incidents = len(incident_events)
        critical_incidents = sum(1 for e in incident_events if "CRITICAL" in e.event_type.upper())

        return OperationResultContext(
            operation_id=str(operation.id),
            organization_id=str(operation.organization.id),
            status=operation.status,
            assigned_at=operation.assigned_at,
            started_at=operation.started_at,
            completed_at=operation.completed_at,
            delay_minutes=operation.delay_minutes,
            planned_deadline=planned_deadline,
            has_thermal_requirement=has_thermal_requirement,
            excursion_count=excursion_count,
            critical_incident_count=critical_incidents,
            total_incident_count=total_incidents,
            all_delivery_stops_completed=all_delivery_completed,
            all_delivery_stops_have_pod=all_delivery_have_pod,
        )
