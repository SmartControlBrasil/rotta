import math
from datetime import datetime, timezone
from src.intelligence.domain.models import OperationContext
from src.intelligence.domain.features import OperationFeatures

class OperationalFeatureExtractor:
    """Extracts a versioned, structured OperationFeatures vector from an OperationContext in memory.

    This extractor is pure Python, deterministic, and does not access any database or external APIs.
    """

    def extract(self, context: OperationContext, reference_time: datetime = None) -> OperationFeatures:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        # 1. Stops Calculations
        total_stops = len(context.stops)
        completed_stops = sum(1 for s in context.stops if s.status == "COMPLETED")
        pending_stops = sum(1 for s in context.stops if s.status in ("PENDING", "ARRIVED"))
        completed_stop_ratio = float(completed_stops) / total_stops if total_stops > 0 else 0.0

        pickup_count = sum(1 for s in context.stops if s.stop_type == "PICKUP")
        delivery_count = sum(1 for s in context.stops if s.stop_type == "DELIVERY")
        stop_delay_min = context.sla.delay_minutes

        # 2. SLA Calculations
        has_sla = context.sla.planned_deadline is not None
        sla_margin_min = None
        if has_sla and context.sla.planned_deadline:
            margin_td = context.sla.planned_deadline - reference_time
            sla_margin_min = margin_td.total_seconds() / 60.0

        sla_overdue = False
        if context.sla.status in ("BREACHED", "DELAYED", "COMPLETED_LATE"):
            sla_overdue = True
        elif has_sla and context.sla.planned_deadline and reference_time > context.sla.planned_deadline and context.status != "COMPLETED":
            sla_overdue = True

        # 3. Tracking Calculations
        tracking_active = context.tracking.has_active_session
        tracking_point_count = context.tracking.total_points

        last_position_age_min = None
        if context.tracking.last_timestamp:
            age_td = reference_time - context.tracking.last_timestamp
            last_position_age_min = age_td.total_seconds() / 60.0

        # 4. Geodetic Remaining Distance (Haversine)
        remaining_distance_km = None
        has_gps = context.tracking.last_latitude is not None and context.tracking.last_longitude is not None

        # Find the final delivery stop
        delivery_stops = [s for s in context.stops if s.stop_type == "DELIVERY"]
        final_delivery_stop = max(delivery_stops, key=lambda s: s.sequence) if delivery_stops else None
        has_destination = final_delivery_stop and final_delivery_stop.latitude is not None and final_delivery_stop.longitude is not None

        if has_gps and has_destination:
            remaining_distance_km = self._haversine(
                context.tracking.last_latitude,
                context.tracking.last_longitude,
                final_delivery_stop.latitude,
                final_delivery_stop.longitude
            )

        # 5. Thermal Calculations
        has_thermal_requirement = context.thermal.temperature_min_c is not None or context.thermal.temperature_max_c is not None
        last_temperature_c = context.thermal.last_reading

        temperature_below_min = None
        temperature_above_max = None
        if has_thermal_requirement and last_temperature_c is not None:
            if context.thermal.temperature_min_c is not None:
                temperature_below_min = last_temperature_c < context.thermal.temperature_min_c
            if context.thermal.temperature_max_c is not None:
                temperature_above_max = last_temperature_c > context.thermal.temperature_max_c

        # 6. Incident Calculations
        incident_count = len(context.incidents)
        open_incident_count = len(context.incidents)  # default behavior, can be enriched
        critical_incident_count = sum(1 for i in context.incidents if "CRITICAL" in i.event_type.upper())

        # 7. Cargo Calculations
        cargo_lot_count = len(context.cargo_lots)
        total_weight_kg = sum(lot.weight_kg for lot in context.cargo_lots)
        total_volume_m3 = sum(lot.volume_m3 for lot in context.cargo_lots)
        total_package_count = 0  # not present in CargoLotContext DTO, documented as gap

        # 8. Complexity Calculations
        multi_stop = total_stops > 2
        multi_pickup = pickup_count > 1
        multi_delivery = delivery_count > 1
        fractional_cargo = cargo_lot_count > 1

        # 9. Driver/Vehicle Features
        has_driver = context.driver is not None
        has_vehicle = context.vehicle is not None

        return OperationFeatures(
            operation_id=context.operation_id,
            feature_schema_version="1.0",
            remaining_distance_km=remaining_distance_km,
            remaining_time_min=None,  # needs prediction model or route engine
            average_speed_kmh=None,  # needs historic route telemetry analysis
            stop_delay_min=stop_delay_min,
            driver_on_time_ratio=None,  # needs historic driver behavior database
            route_deviation_km=None,  # needs geometric route boundary mapping
            thermal_excursion_count=context.thermal.excursion_count,
            incident_count=incident_count,
            total_stops=total_stops,
            completed_stops=completed_stops,
            pending_stops=pending_stops,
            completed_stop_ratio=completed_stop_ratio,
            pickup_count=pickup_count,
            delivery_count=delivery_count,
            has_sla=has_sla,
            sla_margin_min=sla_margin_min,
            sla_overdue=sla_overdue,
            tracking_active=tracking_active,
            tracking_point_count=tracking_point_count,
            last_speed_kmh=None,  # residual database gap
            last_position_age_min=last_position_age_min,
            has_thermal_requirement=has_thermal_requirement,
            temperature_below_min=temperature_below_min,
            temperature_above_max=temperature_above_max,
            last_temperature_c=last_temperature_c,
            open_incident_count=open_incident_count,
            critical_incident_count=critical_incident_count,
            cargo_lot_count=cargo_lot_count,
            total_weight_kg=total_weight_kg,
            total_volume_m3=total_volume_m3,
            total_package_count=total_package_count,
            multi_stop=multi_stop,
            multi_pickup=multi_pickup,
            multi_delivery=multi_delivery,
            fractional_cargo=fractional_cargo,
            has_driver=has_driver,
            has_vehicle=has_vehicle
        )

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        # Earth radius in kilometers
        R = 6371.0

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c
