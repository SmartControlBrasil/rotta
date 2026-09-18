import pytest
from src.intelligence.domain.features import OperationFeatures
from src.intelligence.domain.models import RiskAssessment
from src.intelligence.domain.enums import RiskLevel, RecommendationType
from src.intelligence.application.recommendation_services import OperationalRecommendationEngine

@pytest.fixture
def healthy_features():
    return OperationFeatures(
        operation_id="op-123",
        feature_schema_version="1.0",
        remaining_distance_km=10.0,
        remaining_time_min=30.0,
        average_speed_kmh=40.0,
        stop_delay_min=0,
        driver_on_time_ratio=1.0,
        route_deviation_km=0.0,
        thermal_excursion_count=0,
        incident_count=0,
        total_stops=2,
        completed_stops=0,
        pending_stops=2,
        completed_stop_ratio=0.0,
        pickup_count=1,
        delivery_count=1,
        has_sla=True,
        sla_margin_min=180.0,
        sla_overdue=False,
        tracking_active=True,
        tracking_point_count=10,
        last_speed_kmh=40.0,
        last_position_age_min=5.0,
        has_thermal_requirement=False,
        temperature_below_min=None,
        temperature_above_max=None,
        last_temperature_c=None,
        open_incident_count=0,
        critical_incident_count=0,
        cargo_lot_count=1,
        total_weight_kg=500.0,
        total_volume_m3=1.5,
        total_package_count=0,
        multi_stop=False,
        multi_pickup=False,
        multi_delivery=False,
        fractional_cargo=False,
        has_driver=True,
        has_vehicle=True
    )

@pytest.fixture
def base_assessment():
    import datetime
    return RiskAssessment(
        operation_id="op-123",
        risk_score=0.0,
        risk_level=RiskLevel.LOW,
        reasons=[],
        contributing_features=[],
        recommended_actions=[],
        model_name="rule_based_operational_risk",
        model_version="1.0",
        feature_schema_version="1.0",
        prediction_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

def test_engine_healthy_operation(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    recommendations = engine.recommend(healthy_features, base_assessment)

    assert len(recommendations) == 0

def test_engine_sla_overdue(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    healthy_features.sla_overdue = True
    base_assessment.risk_score = 0.40
    base_assessment.risk_level = RiskLevel.MEDIUM

    recommendations = engine.recommend(healthy_features, base_assessment)
    assert len(recommendations) == 2

    # Priority desc, type asc:
    # 1. CONTACT_DRIVER (HIGH)
    # 2. REVIEW_DELIVERY_WINDOW (HIGH)
    assert recommendations[0].type == RecommendationType.CONTACT_DRIVER
    assert recommendations[0].priority == "HIGH"
    assert "SLA_OVERDUE" in recommendations[0].source_risk_codes

    assert recommendations[1].type == RecommendationType.REVIEW_DELIVERY_WINDOW
    assert recommendations[1].priority == "HIGH"

def test_engine_thermal_excursion(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    healthy_features.has_thermal_requirement = True
    healthy_features.thermal_excursion_count = 1

    recommendations = engine.recommend(healthy_features, base_assessment)
    assert len(recommendations) == 1
    assert recommendations[0].type == RecommendationType.CHECK_THERMAL_INTEGRITY
    assert recommendations[0].priority == "HIGH"
    assert "THERMAL_EXCURSION" in recommendations[0].source_risk_codes

def test_engine_critical_incident(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    healthy_features.critical_incident_count = 1

    recommendations = engine.recommend(healthy_features, base_assessment)
    assert len(recommendations) == 1
    assert recommendations[0].type == RecommendationType.ESCALATE_INCIDENT
    assert recommendations[0].priority == "CRITICAL"

def test_engine_tracking_stale(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    healthy_features.last_position_age_min = 70.0

    recommendations = engine.recommend(healthy_features, base_assessment)
    assert len(recommendations) == 1
    assert recommendations[0].type == RecommendationType.CHECK_TRACKING
    assert recommendations[0].priority == "MEDIUM"

def test_engine_missing_allocations(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    healthy_features.has_driver = False
    healthy_features.has_vehicle = False

    recommendations = engine.recommend(healthy_features, base_assessment)
    # ASSIGN_DRIVER (MEDIUM), ASSIGN_VEHICLE (MEDIUM)
    assert len(recommendations) == 2
    assert recommendations[0].type == RecommendationType.ASSIGN_DRIVER
    assert recommendations[1].type == RecommendationType.ASSIGN_VEHICLE

def test_engine_deduplication_and_priority_merge(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    # Tracking stale (CHECK_TRACKING -> MEDIUM)
    # Tracking unavailable (CHECK_TRACKING -> HIGH)
    healthy_features.tracking_active = False
    healthy_features.last_position_age_min = 75.0

    recommendations = engine.recommend(healthy_features, base_assessment)
    assert len(recommendations) == 1
    assert recommendations[0].type == RecommendationType.CHECK_TRACKING
    assert recommendations[0].priority == "HIGH"  # merged to maximum priority
    assert "TRACKING_UNAVAILABLE" in recommendations[0].source_risk_codes
    assert "TRACKING_STALE" in recommendations[0].source_risk_codes

def test_engine_determinism(healthy_features, base_assessment):
    engine = OperationalRecommendationEngine()
    healthy_features.sla_overdue = True
    healthy_features.critical_incident_count = 1

    res1 = engine.recommend(healthy_features, base_assessment)
    res2 = engine.recommend(healthy_features, base_assessment)

    assert res1 == res2
