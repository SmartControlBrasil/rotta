import pytest
from datetime import datetime, date, time, timezone
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
)
from src.intelligence.application.feature_services import OperationalFeatureExtractor

@pytest.fixture
def base_context():
    ref_time = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    return OperationContext(
        operation_id="op-123",
        organization_id="org-456",
        status="IN_TRANSIT",
        source_type="MARKETPLACE",
        carrier=CarrierContext(id="c-1", trade_name="Carrier One", status="ACTIVE"),
        driver=DriverContext(id="d-1", full_name="Driver A", email="driver@test.com"),
        vehicle=VehicleContext(id="v-1", plate="ABC-1234", vehicle_type="FTL"),
        stops=[
            StopContext(
                id="s-1", sequence=1, stop_type="PICKUP", status="COMPLETED",
                scheduled_date=date(2026, 8, 23), window_start=time(9, 0), window_end=time(11, 0),
                city="Sao Paulo", state="SP", latitude=-23.550520, longitude=-46.633308,
                arrived_at=None, completed_at=None
            ),
            StopContext(
                id="s-2", sequence=2, stop_type="DELIVERY", status="PENDING",
                scheduled_date=date(2026, 8, 23), window_start=time(14, 0), window_end=time(16, 0),
                city="Rio de Janeiro", state="RJ", latitude=-22.906847, longitude=-43.172896,
                arrived_at=None, completed_at=None
            )
        ],
        cargo_lots=[
            CargoLotContext(
                id="lot-1", description="Electronics", weight_kg=1500.0, volume_m3=3.5,
                pickup_stop_id="s-1", delivery_stop_id="s-2"
            )
        ],
        sla=SLAContext(
            status="ON_TIME",
            planned_deadline=datetime(2026, 8, 23, 16, 0, 0, tzinfo=timezone.utc),
            delay_minutes=0
        ),
        tracking=TrackingContext(
            has_active_session=True,
            last_latitude=-23.000000,
            last_longitude=-45.000000,
            last_timestamp=datetime(2026, 8, 23, 11, 50, 0, tzinfo=timezone.utc),
            total_points=42
        ),
        incidents=[],
        thermal=ThermalContext(
            temperature_min_c=2.0,
            temperature_max_c=8.0,
            last_reading=5.0,
            last_reading_at=datetime(2026, 8, 23, 11, 55, 0, tzinfo=timezone.utc),
            excursion_count=0,
            is_in_excursion=False
        ),
        events=[]
    )

def test_extractor_basic_features(base_context):
    extractor = OperationalFeatureExtractor()
    ref_time = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    features = extractor.extract(base_context, reference_time=ref_time)

    assert features.operation_id == "op-123"
    assert features.feature_schema_version == "1.0"

    # Stops
    assert features.total_stops == 2
    assert features.completed_stops == 1
    assert features.pending_stops == 1
    assert features.completed_stop_ratio == 0.5
    assert features.pickup_count == 1
    assert features.delivery_count == 1

    # SLA
    assert features.has_sla is True
    # 4 hours from 12:00 to 16:00
    assert features.sla_margin_min == 240.0
    assert features.sla_overdue is False

    # Tracking
    assert features.tracking_active is True
    assert features.tracking_point_count == 42
    # age = 10 minutes (12:00 - 11:50)
    assert features.last_position_age_min == 10.0

    # Thermal
    assert features.has_thermal_requirement is True
    assert features.temperature_below_min is False
    assert features.temperature_above_max is False
    assert features.last_temperature_c == 5.0

    # Cargo
    assert features.cargo_lot_count == 1
    assert features.total_weight_kg == 1500.0
    assert features.total_volume_m3 == 3.5

    # Driver & Vehicle
    assert features.has_driver is True
    assert features.has_vehicle is True

    # Complexity
    assert features.multi_stop is False
    assert features.multi_pickup is False
    assert features.multi_delivery is False
    assert features.fractional_cargo is False

def test_extractor_haversine_distance(base_context):
    extractor = OperationalFeatureExtractor()
    # last tracking location: (-23.0, -45.0)
    # destination stop: (-22.906847, -43.172896) (s-2)
    # Distance is approx 187.6 km geodetically

    features = extractor.extract(base_context)
    assert features.remaining_distance_km is not None
    assert abs(features.remaining_distance_km - 187.6) < 1.0

def test_extractor_thermal_excursions(base_context):
    extractor = OperationalFeatureExtractor()

    # Test temperature above max limit
    base_context.thermal.last_reading = 10.0
    features = extractor.extract(base_context)
    assert features.temperature_above_max is True
    assert features.temperature_below_min is False

    # Test temperature below min limit
    base_context.thermal.last_reading = 1.0
    features = extractor.extract(base_context)
    assert features.temperature_above_max is False
    assert features.temperature_below_min is True

def test_extractor_missing_values_isolation():
    # Context with almost no telemetry, no driver/vehicle, no SLA
    context = OperationContext(
        operation_id="op-empty",
        organization_id="org-empty",
        status="ASSIGNED",
        source_type="DIRECT",
        carrier=None,
        driver=None,
        vehicle=None,
        stops=[],
        cargo_lots=[],
        sla=SLAContext(status="UNKNOWN", planned_deadline=None, delay_minutes=0),
        tracking=TrackingContext(
            has_active_session=False,
            last_latitude=None, last_longitude=None, last_timestamp=None,
            total_points=0
        ),
        incidents=[],
        thermal=ThermalContext(
            temperature_min_c=None, temperature_max_c=None,
            last_reading=None, last_reading_at=None,
            excursion_count=0, is_in_excursion=False
        ),
        events=[]
    )

    extractor = OperationalFeatureExtractor()
    features = extractor.extract(context)

    assert features.has_driver is False
    assert features.has_vehicle is False
    assert features.total_stops == 0
    assert features.completed_stops == 0
    assert features.completed_stop_ratio == 0.0
    assert features.has_sla is False
    assert features.sla_margin_min is None
    assert features.sla_overdue is False
    assert features.tracking_active is False
    assert features.last_position_age_min is None
    assert features.remaining_distance_km is None
    assert features.has_thermal_requirement is False
    assert features.temperature_below_min is None
    assert features.temperature_above_max is None
    assert features.last_temperature_c is None
    assert features.cargo_lot_count == 0
    assert features.total_weight_kg == 0.0

def test_extractor_determinism(base_context):
    extractor = OperationalFeatureExtractor()
    ref_time = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    res1 = extractor.extract(base_context, reference_time=ref_time)
    res2 = extractor.extract(base_context, reference_time=ref_time)

    assert res1 == res2
