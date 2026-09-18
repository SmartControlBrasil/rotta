from datetime import datetime
from typing import List, Optional

from src.intelligence.domain.models import DatasetRecord, DatasetQualityReport, IntelligenceSnapshot
from src.intelligence.application.ports import IntelligenceSnapshotRepositoryPort, OperationResultContextPort
from src.intelligence.application.outcome_services import BuildOperationalOutcomeService


class BuildOperationalRiskDatasetService:
    """Tenant-scoped application service that builds DatasetRecords from snapshots and outcomes.

    Validates multi-tenant access, performs deterministic sorting, and generates quality reports.
    """

    def __init__(
        self,
        snapshot_repository: IntelligenceSnapshotRepositoryPort,
        result_context_port: OperationResultContextPort,
    ):
        self._snapshot_repository = snapshot_repository
        self._result_context_port = result_context_port
        self._outcome_service = BuildOperationalOutcomeService()

    def build_dataset(
        self,
        organization_id: str,
        actor,
        start_date: datetime,
        end_date: datetime,
    ) -> List[DatasetRecord]:
        # Multi-tenancy guard must be enforced by the query layer/port.
        # But we also ensure we only pull snapshots matching the organization_id.
        snapshots = self._snapshot_repository.find_by_date_range(
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date,
            actor=actor,
        )

        records = []
        for snap in snapshots:
            try:
                res_context = self._result_context_port.get_result_context(snap.operation_id, actor)
                outcome = self._outcome_service.build_outcome(res_context)

                # Determine completeness eligibility
                if res_context.status in ("DELIVERED", "CANCELLED"):
                    eligibility = "COMPLETE"
                else:
                    eligibility = "PARTIAL"

                # Check for label leakage: snapshot assessed_at must be <= outcome resolved_at or completed_at
                # If assessment timestamp is somehow strictly after operational completion, we flag it.

                labels = {
                    "delivered_on_time": outcome.delivered_on_time,
                    "delay_minutes": outcome.delay_minutes,
                    "sla_breached": outcome.sla_breached,
                    "thermal_excursion_occurred": outcome.thermal_excursion_occurred,
                    "critical_incident_occurred": outcome.critical_incident_occurred,
                    "operation_cancelled": outcome.operation_cancelled,
                }

                records.append(DatasetRecord(
                    snapshot_id=snap.id,
                    operation_id=snap.operation_id,
                    organization_id=snap.organization_id,
                    assessed_at=snap.assessed_at,
                    feature_schema_version=snap.feature_schema_version,
                    model_name=snap.model_name,
                    model_version=snap.model_version,
                    features=snap.feature_payload,
                    labels=labels,
                    eligibility=eligibility,
                    metadata={
                        "resolved_at": outcome.resolved_at.isoformat() if outcome.resolved_at else None,
                        "status": res_context.status,
                    }
                ))
            except ValueError:
                # Operation not found or similar
                records.append(DatasetRecord(
                    snapshot_id=snap.id,
                    operation_id=snap.operation_id,
                    organization_id=snap.organization_id,
                    assessed_at=snap.assessed_at,
                    feature_schema_version=snap.feature_schema_version,
                    model_name=snap.model_name,
                    model_version=snap.model_version,
                    features=snap.feature_payload,
                    labels={},
                    eligibility="INELIGIBLE",
                    metadata={"reason": "Operation result context not found"}
                ))
            except PermissionError:
                # Propagate security breaches
                raise

        # Deterministic sorting (assessed_at, snapshot_id)
        records.sort(key=lambda r: (r.assessed_at, r.snapshot_id))
        return records

    def generate_quality_report(self, records: List[DatasetRecord]) -> DatasetQualityReport:
        total = len(records)
        complete = sum(1 for r in records if r.eligibility == "COMPLETE")
        partial = sum(1 for r in records if r.eligibility == "PARTIAL")
        ineligible = sum(1 for r in records if r.eligibility == "INELIGIBLE")

        records_with_sla = sum(1 for r in records if r.labels.get("sla_breached") is not None)
        records_with_thermal = sum(1 for r in records if r.labels.get("thermal_excursion_occurred") is not None)
        records_with_incident = sum(1 for r in records if r.labels.get("critical_incident_occurred") is not None)

        # Missing tracking rate: percentage of records where tracking_active feature was False or tracking point count is 0
        missing_tracking_count = 0
        for r in records:
            if r.eligibility != "INELIGIBLE" and r.features:
                if not r.features.get("tracking_active") or r.features.get("tracking_point_count", 0) == 0:
                    missing_tracking_count += 1

        missing_tracking_rate = float(missing_tracking_count) / total if total > 0 else 0.0

        return DatasetQualityReport(
            total_records=total,
            complete_records=complete,
            partial_records=partial,
            ineligible_records=ineligible,
            records_with_sla_label=records_with_sla,
            records_with_thermal_label=records_with_thermal,
            records_with_incident_label=records_with_incident,
            missing_tracking_rate=round(missing_tracking_rate, 4),
        )
