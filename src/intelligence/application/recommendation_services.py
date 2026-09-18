from typing import List, Dict
from src.intelligence.domain.enums import RecommendationType
from src.intelligence.domain.models import Recommendation, RiskAssessment
from src.intelligence.domain.features import OperationFeatures

PRIORITY_ORDER = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4
}

class OperationalRecommendationEngine:
    """Deterministic, pure Python recommendation engine.

    Translates OperationFeatures and RiskAssessment into structured Recommendation objects.
    Enforces deduplication, priority merging, and deterministic sorting.
    """

    def recommend(self, features: OperationFeatures, assessment: RiskAssessment) -> List[Recommendation]:
        operation_id = features.operation_id
        candidates: List[Recommendation] = []

        # 1. Map SLA features
        if features.sla_overdue:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.REVIEW_DELIVERY_WINDOW,
                priority="HIGH",
                reason="SLA da operação já está vencido.",
                suggested_action="Revisar as janelas de entrega planejadas das paradas da rota.",
                confidence=1.0,
                reason_code="SLA_OVERDUE",
                source_risk_codes=["SLA_OVERDUE"]
            ))
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.CONTACT_DRIVER,
                priority="HIGH",
                reason="SLA da operação já está vencido.",
                suggested_action="Contatar o motorista para obter uma previsão real atualizada.",
                confidence=0.9,
                reason_code="SLA_OVERDUE",
                source_risk_codes=["SLA_OVERDUE"]
            ))
        elif features.has_sla and features.sla_margin_min is not None:
            if features.sla_margin_min < 30:
                candidates.append(Recommendation(
                    operation_id=operation_id,
                    type=RecommendationType.PRIORITIZE_OPERATION,
                    priority="HIGH",
                    reason="Margem de SLA crítica (menos de 30 minutos).",
                    suggested_action="Dar prioridade máxima no descarregamento do veículo na próxima parada.",
                    confidence=0.95,
                    reason_code="SLA_MARGIN_CRITICAL",
                    source_risk_codes=["SLA_MARGIN_CRITICAL"]
                ))
            elif features.sla_margin_min < 120:
                candidates.append(Recommendation(
                    operation_id=operation_id,
                    type=RecommendationType.MONITOR_OPERATION,
                    priority="MEDIUM",
                    reason="Margem de SLA baixa (menos de 2 horas).",
                    suggested_action="Acompanhar velocidade média e estimativa de tráfego do veículo.",
                    confidence=0.8,
                    reason_code="SLA_MARGIN_LOW",
                    source_risk_codes=["SLA_MARGIN_LOW"]
                ))

        # 2. Map Tracking features
        # If driver and vehicle are assigned but tracking is not active
        if features.has_driver and features.has_vehicle and not features.tracking_active:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.CHECK_TRACKING,
                priority="HIGH",
                reason="Rastreamento inativo em operação com motorista e veículo associados.",
                suggested_action="Verificar se o aplicativo de rastreamento do motorista está ativo.",
                confidence=0.9,
                reason_code="TRACKING_UNAVAILABLE",
                source_risk_codes=["TRACKING_UNAVAILABLE"]
            ))
        if features.last_position_age_min is not None and features.last_position_age_min > 60:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.CHECK_TRACKING,
                priority="MEDIUM",
                reason=f"Rastreamento estagnado (sem novas posições há mais de 1 hora).",
                suggested_action="Solicitar reativação do sinal de GPS do motorista.",
                confidence=0.8,
                reason_code="TRACKING_STALE",
                source_risk_codes=["TRACKING_STALE"]
            ))

        # 3. Map Thermal features
        if features.has_thermal_requirement:
            is_anomaly = (
                features.thermal_excursion_count > 0 or
                features.temperature_below_min or
                features.temperature_above_max
            )
            if is_anomaly:
                reasons_list = []
                codes = []
                if features.thermal_excursion_count > 0:
                    reasons_list.append("Excursão térmica detectada.")
                    codes.append("THERMAL_EXCURSION")
                if features.temperature_below_min:
                    reasons_list.append("Temperatura abaixo do mínimo permitido.")
                    codes.append("THERMAL_BELOW_MIN")
                if features.temperature_above_max:
                    reasons_list.append("Temperatura acima do máximo permitido.")
                    codes.append("THERMAL_ABOVE_MAX")

                candidates.append(Recommendation(
                    operation_id=operation_id,
                    type=RecommendationType.CHECK_THERMAL_INTEGRITY,
                    priority="HIGH",
                    reason=" ".join(reasons_list),
                    suggested_action="Verificar integridade térmica do baú e funcionamento do termostato.",
                    confidence=0.9,
                    reason_code="THERMAL_ANOMALY",
                    source_risk_codes=codes
                ))

        # 4. Map Incident features
        if features.critical_incident_count > 0:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.ESCALATE_INCIDENT,
                priority="CRITICAL",
                reason="Incidente crítico registrado na timeline.",
                suggested_action="Escalar a ocorrência de segurança para a gerência de risco imediatamente.",
                confidence=1.0,
                reason_code="CRITICAL_INCIDENT",
                source_risk_codes=["CRITICAL_INCIDENT"]
            ))
        elif features.open_incident_count > 0:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.MONITOR_OPERATION,
                priority="MEDIUM",
                reason="Incidente ativo registrado na timeline.",
                suggested_action="Acompanhar evolução do incidente reportado na timeline.",
                confidence=0.8,
                reason_code="OPEN_INCIDENT",
                source_risk_codes=["OPEN_INCIDENT"]
            ))

        # 5. Map Allocation features
        if not features.has_driver:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.ASSIGN_DRIVER,
                priority="MEDIUM",
                reason="Nenhum motorista alocado para a operação.",
                suggested_action="Selecionar e vincular motorista homologado à operação de frete.",
                confidence=0.85,
                reason_code="NO_DRIVER_ASSIGNED",
                source_risk_codes=["NO_DRIVER_ASSIGNED"]
            ))
        if not features.has_vehicle:
            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.ASSIGN_VEHICLE,
                priority="MEDIUM",
                reason="Nenhum veículo alocado para a operação.",
                suggested_action="Vincular veículo compatível para transporte da carga.",
                confidence=0.85,
                reason_code="NO_VEHICLE_ASSIGNED",
                source_risk_codes=["NO_VEHICLE_ASSIGNED"]
            ))

        # 6. Map Complexity (low priority warnings)
        if features.multi_stop or features.fractional_cargo:
            reasons_list = []
            codes = []
            if features.multi_stop:
                reasons_list.append("Operação multi-stop cadastrada.")
                codes.append("MULTI_STOP")
            if features.fractional_cargo:
                reasons_list.append("Carga fracionada cadastrada.")
                codes.append("FRACTIONAL_CARGO")

            candidates.append(Recommendation(
                operation_id=operation_id,
                type=RecommendationType.MONITOR_OPERATION,
                priority="LOW",
                reason=" ".join(reasons_list),
                suggested_action="Monitorar rotas com múltiplas coletas e entregas.",
                confidence=0.7,
                reason_code="COMPLEXITY_WARNING",
                source_risk_codes=codes
            ))

        # 7. Deduplicate and Merge
        merged: Dict[RecommendationType, Recommendation] = {}
        for cand in candidates:
            rec_type = cand.type
            if rec_type in merged:
                existing = merged[rec_type]
                # Compare priorities
                if PRIORITY_ORDER[cand.priority] > PRIORITY_ORDER[existing.priority]:
                    existing.priority = cand.priority
                    existing.suggested_action = cand.suggested_action
                    existing.reason_code = cand.reason_code

                existing.reason = existing.reason + " " + cand.reason
                existing.confidence = max(existing.confidence, cand.confidence)
                existing.source_risk_codes = list(set(existing.source_risk_codes + cand.source_risk_codes))
            else:
                merged[rec_type] = cand

        # 8. Deterministic Sort (priority desc, type asc)
        sorted_recs = sorted(
            merged.values(),
            key=lambda r: (-PRIORITY_ORDER[r.priority], r.type.value)
        )

        return sorted_recs
