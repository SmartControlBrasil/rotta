from datetime import datetime, timezone
from typing import Optional
from src.intelligence.domain.models import OperationResultContext, OperationalOutcome


class BuildOperationalOutcomeService:
    """Computes the ground truth OperationalOutcome from an OperationResultContext.

    This service is pure Python and encapsulates the outcome business rules.
    """

    def build_outcome(self, context: OperationResultContext) -> OperationalOutcome:
        operation_id = context.operation_id
        status = context.status

        # 1. SLA labels
        delivered_on_time = None
        delay_minutes = None
        sla_breached = None

        # Determine delay
        if status == "DELIVERED":
            if context.delay_minutes is not None:
                delay_minutes = context.delay_minutes
            elif context.completed_at and context.planned_deadline:
                delay_td = context.completed_at - context.planned_deadline
                delay_minutes = int(delay_td.total_seconds() / 60)

            if delay_minutes is not None:
                delivered_on_time = delay_minutes <= 0
                sla_breached = delay_minutes > 0
        elif status == "CANCELLED":
            delivered_on_time = None
            sla_breached = True  # A cancelled operation failed its SLA
            if context.planned_deadline and context.completed_at:
                delay_td = context.completed_at - context.planned_deadline
                delay_minutes = int(delay_td.total_seconds() / 60)
        else:
            # Operation is in progress - outcome is not final
            delivered_on_time = None
            if context.planned_deadline:
                # If deadline passed while in progress
                now = datetime.now(timezone.utc)
                if now > context.planned_deadline:
                    sla_breached = True
                    delay_td = now - context.planned_deadline
                    delay_minutes = int(delay_td.total_seconds() / 60)
                else:
                    sla_breached = False
                    delay_minutes = 0

        # 2. Thermal labels
        thermal_excursion_occurred = None
        if context.has_thermal_requirement:
            thermal_excursion_occurred = context.excursion_count > 0

        # 3. Incident labels
        critical_incident_occurred = context.critical_incident_count > 0

        # 4. Cancellation label
        operation_cancelled = status == "CANCELLED"

        # 5. Resolved timestamp
        resolved_at = None
        if status in ("DELIVERED", "CANCELLED"):
            resolved_at = context.completed_at

        return OperationalOutcome(
            operation_id=operation_id,
            delivered_on_time=delivered_on_time,
            delay_minutes=delay_minutes,
            sla_breached=sla_breached,
            thermal_excursion_occurred=thermal_excursion_occurred,
            critical_incident_occurred=critical_incident_occurred,
            operation_cancelled=operation_cancelled,
            resolved_at=resolved_at,
        )
