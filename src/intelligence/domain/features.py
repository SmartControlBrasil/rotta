from dataclasses import dataclass
from typing import Optional

@dataclass
class OperationFeatures:
    operation_id: str
    feature_schema_version: str

    # --- Existing Features ---
    remaining_distance_km: Optional[float] = None
    remaining_time_min: Optional[float] = None
    average_speed_kmh: Optional[float] = None
    stop_delay_min: int = 0
    driver_on_time_ratio: Optional[float] = None
    route_deviation_km: Optional[float] = None
    thermal_excursion_count: int = 0
    incident_count: int = 0

    # --- Stops Features ---
    total_stops: int = 0
    completed_stops: int = 0
    pending_stops: int = 0
    completed_stop_ratio: float = 0.0
    pickup_count: int = 0
    delivery_count: int = 0

    # --- SLA Features ---
    has_sla: bool = False
    sla_margin_min: Optional[float] = None
    sla_overdue: bool = False

    # --- Tracking Features ---
    tracking_active: bool = False
    tracking_point_count: int = 0
    last_speed_kmh: Optional[float] = None
    last_position_age_min: Optional[float] = None

    # --- Thermal Features ---
    has_thermal_requirement: bool = False
    temperature_below_min: Optional[bool] = None
    temperature_above_max: Optional[bool] = None
    last_temperature_c: Optional[float] = None

    # --- Incident Features ---
    open_incident_count: int = 0
    critical_incident_count: int = 0

    # --- Cargo Features ---
    cargo_lot_count: int = 0
    total_weight_kg: float = 0.0
    total_volume_m3: float = 0.0
    total_package_count: int = 0

    # --- Complexity Features ---
    multi_stop: bool = False
    multi_pickup: bool = False
    multi_delivery: bool = False
    fractional_cargo: bool = False

    # --- Driver/Vehicle Features ---
    has_driver: bool = False
    has_vehicle: bool = False
