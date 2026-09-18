import hashlib
import json
from datetime import datetime, date, time
from decimal import Decimal
from enum import Enum
from typing import Any, List

from src.intelligence.domain.features import OperationFeatures
from src.intelligence.domain.models import RiskAssessment, Recommendation


def _serialize_value(value: Any) -> Any:
    """Recursively serialize a value for JSON storage."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (int, bool, str)):
        return value
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return str(value)


class IntelligencePayloadSerializer:
    """Explicit, deterministic serializer for intelligence payloads.

    Handles datetime (ISO 8601 UTC), Decimal (string), Enum (.value),
    None (preserved), float (6 decimal places).
    """

    @staticmethod
    def serialize_features(features: OperationFeatures) -> dict:
        return {
            "operation_id": features.operation_id,
            "feature_schema_version": features.feature_schema_version,
            "remaining_distance_km": _serialize_value(features.remaining_distance_km),
            "remaining_time_min": _serialize_value(features.remaining_time_min),
            "average_speed_kmh": _serialize_value(features.average_speed_kmh),
            "stop_delay_min": features.stop_delay_min,
            "driver_on_time_ratio": _serialize_value(features.driver_on_time_ratio),
            "route_deviation_km": _serialize_value(features.route_deviation_km),
            "thermal_excursion_count": features.thermal_excursion_count,
            "incident_count": features.incident_count,
            "total_stops": features.total_stops,
            "completed_stops": features.completed_stops,
            "pending_stops": features.pending_stops,
            "completed_stop_ratio": _serialize_value(features.completed_stop_ratio),
            "pickup_count": features.pickup_count,
            "delivery_count": features.delivery_count,
            "has_sla": features.has_sla,
            "sla_margin_min": _serialize_value(features.sla_margin_min),
            "sla_overdue": features.sla_overdue,
            "tracking_active": features.tracking_active,
            "tracking_point_count": features.tracking_point_count,
            "last_speed_kmh": _serialize_value(features.last_speed_kmh),
            "last_position_age_min": _serialize_value(features.last_position_age_min),
            "has_thermal_requirement": features.has_thermal_requirement,
            "temperature_below_min": _serialize_value(features.temperature_below_min),
            "temperature_above_max": _serialize_value(features.temperature_above_max),
            "last_temperature_c": _serialize_value(features.last_temperature_c),
            "open_incident_count": features.open_incident_count,
            "critical_incident_count": features.critical_incident_count,
            "cargo_lot_count": features.cargo_lot_count,
            "total_weight_kg": _serialize_value(features.total_weight_kg),
            "total_volume_m3": _serialize_value(features.total_volume_m3),
            "total_package_count": features.total_package_count,
            "multi_stop": features.multi_stop,
            "multi_pickup": features.multi_pickup,
            "multi_delivery": features.multi_delivery,
            "fractional_cargo": features.fractional_cargo,
            "has_driver": features.has_driver,
            "has_vehicle": features.has_vehicle,
        }

    @staticmethod
    def serialize_risk(assessment: RiskAssessment) -> dict:
        return {
            "operation_id": assessment.operation_id,
            "risk_score": _serialize_value(assessment.risk_score),
            "risk_level": _serialize_value(assessment.risk_level),
            "reasons": assessment.reasons,
            "contributing_features": assessment.contributing_features,
            "recommended_actions": assessment.recommended_actions,
            "model_name": assessment.model_name,
            "model_version": assessment.model_version,
            "feature_schema_version": assessment.feature_schema_version,
            "prediction_timestamp": _serialize_value(assessment.prediction_timestamp),
        }

    @staticmethod
    def serialize_recommendations(recommendations: List[Recommendation]) -> list:
        return [
            {
                "operation_id": rec.operation_id,
                "type": _serialize_value(rec.type),
                "priority": rec.priority,
                "reason": rec.reason,
                "suggested_action": rec.suggested_action,
                "confidence": _serialize_value(rec.confidence),
                "reason_code": rec.reason_code,
                "source_risk_codes": rec.source_risk_codes,
            }
            for rec in recommendations
        ]

    @staticmethod
    def compute_fingerprint(feature_payload: dict, model_version: str, feature_schema_version: str) -> str:
        canonical = json.dumps(
            {
                "features": feature_payload,
                "model_version": model_version,
                "feature_schema_version": feature_schema_version,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
