from datetime import datetime
from typing import Optional, List

from src.intelligence.domain.models import OperationIntelligenceDTO
from src.intelligence.application.ports import IntelligenceSnapshotRepositoryPort


class OperationIntelligenceQueryService:
    """Tenant-scoped application service that retrieves operational intelligence read models.

    Ensures multi-tenant isolation and prevents N+1 query overhead for batch operations.
    """

    def __init__(self, snapshot_repository: IntelligenceSnapshotRepositoryPort):
        self._repo = snapshot_repository

    def get_latest_assessment(self, operation_id: str, organization_id: str, actor) -> OperationIntelligenceDTO:
        from src.organizations.infrastructure.django.models import Membership
        from django.core.exceptions import PermissionDenied

        # Tenant isolation check
        if not getattr(actor, "is_superuser", False):
            has_access = Membership.objects.filter(
                user=actor,
                organization_id=organization_id,
                status="ACTIVE"
            ).exists()
            if not has_access:
                raise PermissionDenied("Acesso negado: ator não pertence à organização da operação.")

        snapshot = self._repo.latest_for_operation(operation_id, organization_id)
        if snapshot is None:
            return OperationIntelligenceDTO(
                operation_id=operation_id,
                risk_score=None,
                risk_level="NOT_ASSESSED",
                assessed_at=None,
                reasons=[],
                recommendations=[],
                model_version=None,
                feature_schema_version=None
            )

        return OperationIntelligenceDTO(
            operation_id=snapshot.operation_id,
            risk_score=snapshot.risk_score,
            risk_level=snapshot.risk_level.value if hasattr(snapshot.risk_level, "value") else str(snapshot.risk_level),
            assessed_at=snapshot.assessed_at,
            reasons=snapshot.risk_payload.get("reasons", []),
            recommendations=snapshot.recommendation_payload,
            model_version=snapshot.model_version,
            feature_schema_version=snapshot.feature_schema_version
        )

    def get_assessment_history(self, operation_id: str, organization_id: str, actor) -> List[OperationIntelligenceDTO]:
        from src.organizations.infrastructure.django.models import Membership
        from django.core.exceptions import PermissionDenied

        # Tenant isolation check
        if not getattr(actor, "is_superuser", False):
            has_access = Membership.objects.filter(
                user=actor,
                organization_id=organization_id,
                status="ACTIVE"
            ).exists()
            if not has_access:
                raise PermissionDenied("Acesso negado: ator não pertence à organização da operação.")

        snapshots = self._repo.history_for_operation(operation_id, organization_id)
        return [
            OperationIntelligenceDTO(
                operation_id=snap.operation_id,
                risk_score=snap.risk_score,
                risk_level=snap.risk_level.value if hasattr(snap.risk_level, "value") else str(snap.risk_level),
                assessed_at=snap.assessed_at,
                reasons=snap.risk_payload.get("reasons", []),
                recommendations=snap.recommendation_payload,
                model_version=snap.model_version,
                feature_schema_version=snap.feature_schema_version
            )
            for snap in snapshots
        ]

    def get_latest_assessments_for_operations(self, operation_ids: List[str], actor) -> dict[str, OperationIntelligenceDTO]:
        from src.intelligence.infrastructure.django.models import IntelligenceAssessmentRecord
        from src.organizations.infrastructure.django.models import Membership

        result = {}
        for op_id in operation_ids:
            result[op_id] = OperationIntelligenceDTO(
                operation_id=op_id,
                risk_score=None,
                risk_level="NOT_ASSESSED",
                assessed_at=None,
                reasons=[],
                recommendations=[],
                model_version=None,
                feature_schema_version=None
            )

        import uuid
        valid_uuids = []
        for op_id in operation_ids:
            try:
                valid_uuids.append(uuid.UUID(str(op_id)))
            except ValueError:
                pass

        if not valid_uuids:
            return result

        records_query = IntelligenceAssessmentRecord.objects.filter(operation_id__in=valid_uuids)

        if not getattr(actor, "is_superuser", False):
            user_org_ids = list(Membership.objects.filter(user=actor, status="ACTIVE").values_list("organization_id", flat=True))
            records_query = records_query.filter(organization_id__in=user_org_ids)

        # Build subquery to load only the latest ID per operation
        from django.db.models import OuterRef, Subquery
        latest_ids_subquery = IntelligenceAssessmentRecord.objects.filter(
            operation_id=OuterRef("operation_id")
        ).order_by("-assessed_at").values("id")[:1]

        records = records_query.filter(id__in=Subquery(latest_ids_subquery))

        for record in records:
            op_id = str(record.operation_id)
            result[op_id] = OperationIntelligenceDTO(
                operation_id=op_id,
                risk_score=record.risk_score,
                risk_level=record.risk_level,
                assessed_at=record.assessed_at,
                reasons=record.risk_payload.get("reasons", []),
                recommendations=record.recommendation_payload,
                model_version=record.model_version,
                feature_schema_version=record.feature_schema_version
            )

        return result
