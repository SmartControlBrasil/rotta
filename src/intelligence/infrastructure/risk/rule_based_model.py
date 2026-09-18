from datetime import datetime, timezone
from src.intelligence.application.ports import RiskModelPort
from src.intelligence.domain.enums import RiskLevel
from src.intelligence.domain.models import RiskAssessment
from src.intelligence.domain.features import OperationFeatures

# Risk Policy Thresholds & Weights
SLA_OVERDUE_WEIGHT = 0.40
SLA_MARGIN_CRITICAL_WEIGHT = 0.30
SLA_MARGIN_LOW_WEIGHT = 0.15

TRACKING_UNAVAILABLE_WEIGHT = 0.20
TRACKING_STALE_WEIGHT = 0.15

THERMAL_EXCURSION_WEIGHT = 0.25
THERMAL_BELOW_MIN_WEIGHT = 0.20
THERMAL_ABOVE_MAX_WEIGHT = 0.20

CRITICAL_INCIDENT_WEIGHT = 0.35
OPEN_INCIDENT_WEIGHT = 0.15
MULTIPLE_OPEN_INCIDENTS_WEIGHT = 0.20

MULTI_STOP_COMPLEXITY_WEIGHT = 0.05
FRACTIONAL_CARGO_COMPLEXITY_WEIGHT = 0.05

NO_DRIVER_ASSIGNED_WEIGHT = 0.15
NO_VEHICLE_ASSIGNED_WEIGHT = 0.10

class RuleBasedRiskModel(RiskModelPort):
    """Rule-Based Operational Risk Model.

    Calculates risk score deterministically from OperationFeatures using a capped additive approach.
    Explains the score by listing reasons and contributing features.
    """

    def predict(self, features: OperationFeatures) -> RiskAssessment:
        reasons = []
        contributing_features = []
        total_weight = 0.0

        # 1. SLA Rules
        if features.sla_overdue:
            reasons.append("SLA da operação está atrasado.")
            contributing_features.append("sla_overdue")
            total_weight += SLA_OVERDUE_WEIGHT
        elif features.has_sla and features.sla_margin_min is not None:
            if features.sla_margin_min < 30:
                reasons.append("Margem de SLA crítica (menos de 30 minutos).")
                contributing_features.append("sla_margin_min")
                total_weight += SLA_MARGIN_CRITICAL_WEIGHT
            elif features.sla_margin_min < 120:
                reasons.append("Margem de SLA baixa (menos de 2 horas).")
                contributing_features.append("sla_margin_min")
                total_weight += SLA_MARGIN_LOW_WEIGHT

        # 2. Tracking Rules
        if features.has_driver and features.has_vehicle and not features.tracking_active:
            reasons.append("Rastreamento inativo em operação com motorista e veículo associados.")
            contributing_features.append("tracking_active")
            total_weight += TRACKING_UNAVAILABLE_WEIGHT
        elif features.tracking_active and features.last_position_age_min is not None and features.last_position_age_min > 60:
            reasons.append("Rastreamento estagnado (sem novas posições há mais de 1 hora).")
            contributing_features.append("last_position_age_min")
            total_weight += TRACKING_STALE_WEIGHT

        # 3. Thermal Rules
        if features.has_thermal_requirement:
            if features.thermal_excursion_count > 0:
                reasons.append("Ocorrência de variação térmica fora do limite permitido.")
                contributing_features.append("thermal_excursion_count")
                total_weight += THERMAL_EXCURSION_WEIGHT
            if features.temperature_below_min:
                reasons.append("Última temperatura registrada está abaixo do limite mínimo permitido.")
                contributing_features.append("temperature_below_min")
                total_weight += THERMAL_BELOW_MIN_WEIGHT
            if features.temperature_above_max:
                reasons.append("Última temperatura registrada está acima do limite máximo permitido.")
                contributing_features.append("temperature_above_max")
                total_weight += THERMAL_ABOVE_MAX_WEIGHT

        # 4. Incident Rules
        if features.critical_incident_count > 0:
            reasons.append("Incidente crítico registrado na timeline da operação.")
            contributing_features.append("critical_incident_count")
            total_weight += CRITICAL_INCIDENT_WEIGHT
        elif features.open_incident_count > 0:
            reasons.append("Incidentes ativos registrados na timeline da operação.")
            contributing_features.append("open_incident_count")
            total_weight += OPEN_INCIDENT_WEIGHT

        if features.open_incident_count > 1:
            reasons.append("Múltiplos incidentes registrados na timeline da operação.")
            contributing_features.append("open_incident_count")
            total_weight += MULTIPLE_OPEN_INCIDENTS_WEIGHT

        # 5. Complexity Rules
        if features.multi_stop:
            reasons.append("Complexidade moderada devido a múltiplas paradas.")
            contributing_features.append("multi_stop")
            total_weight += MULTI_STOP_COMPLEXITY_WEIGHT
        if features.fractional_cargo:
            reasons.append("Complexidade moderada devido a múltiplos lotes de carga.")
            contributing_features.append("fractional_cargo")
            total_weight += FRACTIONAL_CARGO_COMPLEXITY_WEIGHT

        # 6. Allocation Rules
        if not features.has_driver:
            reasons.append("Nenhum motorista alocado para a operação.")
            contributing_features.append("has_driver")
            total_weight += NO_DRIVER_ASSIGNED_WEIGHT
        if not features.has_vehicle:
            reasons.append("Nenhum veículo alocado para a operação.")
            contributing_features.append("has_vehicle")
            total_weight += NO_VEHICLE_ASSIGNED_WEIGHT

        # 7. Aggregate Score
        risk_score = round(min(1.0, total_weight), 2)

        # 8. Risk Level Mapping
        if risk_score < 0.25:
            risk_level = RiskLevel.LOW
        elif risk_score < 0.50:
            risk_level = RiskLevel.MEDIUM
        elif risk_score < 0.75:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.CRITICAL

        # 9. Action Mitigation Mapping
        recommended_actions = []
        if risk_level == RiskLevel.CRITICAL:
            recommended_actions.append("ALERT_OPERATIONS: Acionar time de monitoramento de emergência imediatamente.")
        if "sla_overdue" in contributing_features or features.sla_overdue:
            recommended_actions.append("CONTACT_CARRIER: Verificar atraso no SLA com a transportadora.")
        if "tracking_active" in contributing_features or "last_position_age_min" in contributing_features:
            recommended_actions.append("CALL_DRIVER: Entrar em contato com o motorista para verificar o sinal de GPS.")
        if "thermal_excursion_count" in contributing_features or features.thermal_excursion_count > 0:
            recommended_actions.append("CHECK_THERMAL: Solicitar verificação do baú frio e regulagem do termostato.")
        if not recommended_actions:
            recommended_actions.append("MONITOR: Continuar acompanhamento rotineiro da operação.")

        return RiskAssessment(
            operation_id=features.operation_id,
            risk_score=risk_score,
            risk_level=risk_level,
            reasons=reasons,
            contributing_features=list(set(contributing_features)),
            recommended_actions=recommended_actions,
            model_name="rule_based_operational_risk",
            model_version="1.0",
            feature_schema_version=features.feature_schema_version,
            prediction_timestamp=datetime.now(timezone.utc)
        )
