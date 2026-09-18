from datetime import datetime, timezone
from typing import Optional
from src.intelligence.domain.features import OperationFeatures
from src.intelligence.domain.models import IntelligenceSnapshot


class OperationalIntelligenceSamplingPolicyV1:
    """Sampling policy that decides when to trigger a new intelligence assessment.

    Prevents high-frequency telemetric noise while guaranteeing that critical
    lifecycle changes and risk transitions are evaluated immediately.
    """

    def __init__(self, debounce_minutes: int = 15):
        self.debounce_seconds = debounce_minutes * 60

    def should_assess(
        self,
        features: OperationFeatures,
        latest_snapshot: Optional[IntelligenceSnapshot],
        event_type: str,
        reference_time: Optional[datetime] = None,
    ) -> bool:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        # 1. No previous snapshot -> Always assess
        if latest_snapshot is None:
            return True

        # 2. Critical events bypass debounce
        critical_events = (
            "OPERATION_STARTED",
            "INCIDENT_REPORTED",
            "POD_CREATED",
            "CANCELLED",
            "STATUS_CHANGED"
        )
        if event_type in critical_events:
            return True

        # 3. Time-based debounce (minimum interval)
        time_elapsed = reference_time - latest_snapshot.assessed_at
        if time_elapsed.total_seconds() >= self.debounce_seconds:
            return True

        # 4. Significant state/risk transition check
        latest_features = latest_snapshot.feature_payload

        # Check risk score transition
        latest_score = latest_snapshot.risk_score

        # Calculate approximate current score for decision (pure Python comparison)
        # Check if critical features changed
        latest_incident_count = latest_features.get("incident_count", 0)
        if features.incident_count != latest_incident_count:
            return True

        latest_excursions = latest_features.get("thermal_excursion_count", 0)
        if features.thermal_excursion_count != latest_excursions:
            return True

        latest_sla_overdue = latest_features.get("sla_overdue", False)
        if features.sla_overdue != latest_sla_overdue:
            return True

        latest_completed_stops = latest_features.get("completed_stops", 0)
        if features.completed_stops != latest_completed_stops:
            return True

        # Otherwise, skip
        return False
