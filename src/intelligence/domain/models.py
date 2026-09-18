from dataclasses import dataclass
from typing import List, Optional
from datetime import date, datetime, time
from src.intelligence.domain.enums import RiskLevel, RecommendationType

@dataclass
class CarrierContext:
    id: str
    trade_name: str
    status: str

@dataclass
class DriverContext:
    id: str
    full_name: str
    email: str

@dataclass
class VehicleContext:
    id: str
    plate: str
    vehicle_type: str

@dataclass
class StopContext:
    id: str
    sequence: int
    stop_type: str  # PICKUP, DELIVERY
    status: str  # PENDING, ARRIVED, COMPLETED
    scheduled_date: date
    window_start: Optional[time]
    window_end: Optional[time]
    city: str
    state: str
    latitude: Optional[float]
    longitude: Optional[float]
    arrived_at: Optional[datetime]
    completed_at: Optional[datetime]

@dataclass
class CargoLotContext:
    id: str
    description: str
    weight_kg: float
    volume_m3: float
    pickup_stop_id: str
    delivery_stop_id: str

@dataclass
class SLAContext:
    status: str  # MET, BREACHED, UNKNOWN
    planned_deadline: Optional[datetime]
    delay_minutes: int

@dataclass
class TrackingContext:
    has_active_session: bool
    last_latitude: Optional[float]
    last_longitude: Optional[float]
    last_timestamp: Optional[datetime]
    total_points: int

@dataclass
class IncidentContext:
    id: str
    event_type: str
    occurred_at: datetime
    description: Optional[str]

@dataclass
class ThermalContext:
    temperature_min_c: Optional[float]
    temperature_max_c: Optional[float]
    last_reading: Optional[float]
    last_reading_at: Optional[datetime]
    excursion_count: int
    is_in_excursion: bool

@dataclass
class EventContext:
    id: str
    event_type: str
    occurred_at: datetime
    actor_username: Optional[str]

@dataclass
class OperationContext:
    operation_id: str
    organization_id: str
    status: str  # OperationStatus value
    source_type: str  # OperationSource value
    carrier: Optional[CarrierContext]
    driver: Optional[DriverContext]
    vehicle: Optional[VehicleContext]
    stops: List[StopContext]
    cargo_lots: List[CargoLotContext]
    sla: SLAContext
    tracking: TrackingContext
    incidents: List[IncidentContext]
    thermal: ThermalContext
    events: List[EventContext]

@dataclass
class RiskAssessment:
    operation_id: str
    risk_score: float  # 0.0 to 1.0
    risk_level: RiskLevel
    reasons: List[str]
    contributing_features: List[str]
    recommended_actions: List[str]
    model_name: str
    model_version: str
    feature_schema_version: str
    prediction_timestamp: datetime

@dataclass
class Recommendation:
    operation_id: str
    type: RecommendationType
    priority: str  # HIGH, MEDIUM, LOW, CRITICAL
    reason: str
    suggested_action: str
    confidence: float
    reason_code: str
    source_risk_codes: List[str]

@dataclass
class IntelligenceSnapshot:
    id: str
    organization_id: str
    operation_id: str
    assessed_at: datetime
    reference_time: datetime
    risk_score: float
    risk_level: RiskLevel
    model_name: str
    model_version: str
    feature_schema_version: str
    recommendation_policy_version: str
    context_fingerprint: str
    feature_payload: dict
    risk_payload: dict
    recommendation_payload: list

@dataclass
class OperationalOutcome:
    operation_id: str
    delivered_on_time: Optional[bool]
    delay_minutes: Optional[int]
    sla_breached: Optional[bool]
    thermal_excursion_occurred: Optional[bool]
    critical_incident_occurred: Optional[bool]
    operation_cancelled: Optional[bool]
    resolved_at: Optional[datetime]

@dataclass
class OperationResultContext:
    operation_id: str
    organization_id: str
    status: str  # OperationStatus value
    assigned_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    delay_minutes: Optional[int]
    planned_deadline: Optional[datetime]
    has_thermal_requirement: bool
    excursion_count: int
    critical_incident_count: int
    total_incident_count: int
    all_delivery_stops_completed: bool
    all_delivery_stops_have_pod: bool


@dataclass
class DatasetRecord:
    snapshot_id: str
    operation_id: str
    organization_id: str
    assessed_at: datetime
    feature_schema_version: str
    model_name: str
    model_version: str
    features: dict
    labels: dict
    eligibility: str  # COMPLETE, PARTIAL, INELIGIBLE
    metadata: dict


@dataclass
class DatasetQualityReport:
    total_records: int
    complete_records: int
    partial_records: int
    ineligible_records: int
    records_with_sla_label: int
    records_with_thermal_label: int
    records_with_incident_label: int
    missing_tracking_rate: float


@dataclass
class DatasetManifest:
    dataset_version: str
    generated_at: datetime
    organization_id: str
    record_count: int
    feature_schema_versions: List[str]
    date_range_start: datetime
    date_range_end: datetime
    quality_summary: dict
    fingerprint: str


@dataclass
class ConfusionMatrix:
    tp: int
    fp: int
    tn: int
    fn: int
    precision: Optional[float]
    recall: Optional[float]
    specificity: Optional[float]


@dataclass
class BaselineEvaluationReport:
    sla_evaluation: ConfusionMatrix
    thermal_evaluation: ConfusionMatrix
    total_evaluated_records: int
    false_positive_rate: float
    false_negative_rate: float


@dataclass
class OperationIntelligenceDTO:
    operation_id: str
    risk_score: Optional[float]
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL, or NOT_ASSESSED
    assessed_at: Optional[datetime]
    reasons: List[str]
    recommendations: List[dict]  # list of serialized recommendations
    model_version: Optional[str]
    feature_schema_version: Optional[str]
