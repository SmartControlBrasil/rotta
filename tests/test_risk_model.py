import pytest
from src.intelligence.domain.features import OperationFeatures
from src.intelligence.domain.enums import RiskLevel
from src.intelligence.infrastructure.risk.rule_based_model import RuleBasedRiskModel

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

def test_risk_model_healthy_features(healthy_features):
    model = RuleBasedRiskModel()
    assessment = model.predict(healthy_features)

    assert assessment.operation_id == "op-123"
    assert assessment.risk_score == 0.0
    assert assessment.risk_level == RiskLevel.LOW
    assert len(assessment.reasons) == 0
    assert len(assessment.contributing_features) == 0

def test_risk_model_sla_overdue(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.sla_overdue = True

    assessment = model.predict(healthy_features)
    assert assessment.risk_score == 0.40
    assert assessment.risk_level == RiskLevel.MEDIUM
    assert "SLA da operação está atrasado." in assessment.reasons
    assert "sla_overdue" in assessment.contributing_features

def test_risk_model_stale_tracking(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.last_position_age_min = 75.0  # > 60 min

    assessment = model.predict(healthy_features)
    assert assessment.risk_score == 0.15
    assert assessment.risk_level == RiskLevel.LOW
    assert "Rastreamento estagnado (sem novas posições há mais de 1 hora)." in assessment.reasons
    assert "last_position_age_min" in assessment.contributing_features

def test_risk_model_critical_incident(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.critical_incident_count = 1

    assessment = model.predict(healthy_features)
    assert assessment.risk_score == 0.35
    assert assessment.risk_level == RiskLevel.MEDIUM
    assert "Incidente crítico registrado na timeline da operação." in assessment.reasons
    assert "critical_incident_count" in assessment.contributing_features

def test_risk_model_thermal_excursion_ignored_if_no_requirement(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.thermal_excursion_count = 2
    healthy_features.has_thermal_requirement = False

    assessment = model.predict(healthy_features)
    assert assessment.risk_score == 0.0
    assert len(assessment.reasons) == 0

def test_risk_model_thermal_excursion_triggered_with_requirement(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.thermal_excursion_count = 2
    healthy_features.has_thermal_requirement = True

    assessment = model.predict(healthy_features)
    assert assessment.risk_score == 0.25
    assert assessment.risk_level == RiskLevel.MEDIUM
    assert "Ocorrência de variação térmica fora do limite permitido." in assessment.reasons

def test_risk_model_multiple_conditions_and_cap(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.sla_overdue = True  # +0.40
    healthy_features.critical_incident_count = 1  # +0.35
    healthy_features.tracking_active = False  # +0.20 (triggered because has_driver and has_vehicle are True)
    healthy_features.has_thermal_requirement = True
    healthy_features.thermal_excursion_count = 1  # +0.25
    # Total sum is 1.20, but must be capped at 1.00

    assessment = model.predict(healthy_features)
    assert assessment.risk_score == 1.00
    assert assessment.risk_level == RiskLevel.CRITICAL
    assert len(assessment.reasons) == 4

def test_risk_model_determinism(healthy_features):
    model = RuleBasedRiskModel()
    healthy_features.sla_overdue = True
    healthy_features.critical_incident_count = 1

    assessment1 = model.predict(healthy_features)
    assessment2 = model.predict(healthy_features)

    assert assessment1.risk_score == assessment2.risk_score
    assert assessment1.reasons == assessment2.reasons
    assert assessment1.contributing_features == assessment2.contributing_features
