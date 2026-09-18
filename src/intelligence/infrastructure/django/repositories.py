from typing import Optional, List
from datetime import datetime

from src.intelligence.application.ports import IntelligenceSnapshotRepositoryPort
from src.intelligence.domain.models import IntelligenceSnapshot
from src.intelligence.domain.enums import RiskLevel
from src.intelligence.infrastructure.django.models import IntelligenceAssessmentRecord


class DjangoIntelligenceSnapshotRepository(IntelligenceSnapshotRepositoryPort):
    """Django ORM adapter for persisting and querying intelligence assessment snapshots.

    All queries enforce organization_id filtering for multi-tenant isolation.
    """

    def save(self, snapshot: IntelligenceSnapshot) -> IntelligenceSnapshot:
        record = IntelligenceAssessmentRecord(
            id=snapshot.id,
            organization_id=snapshot.organization_id,
            operation_id=snapshot.operation_id,
            assessed_at=snapshot.assessed_at,
            reference_time=snapshot.reference_time,
            risk_score=snapshot.risk_score,
            risk_level=snapshot.risk_level.value if isinstance(snapshot.risk_level, RiskLevel) else snapshot.risk_level,
            model_name=snapshot.model_name,
            model_version=snapshot.model_version,
            feature_schema_version=snapshot.feature_schema_version,
            recommendation_policy_version=snapshot.recommendation_policy_version,
            context_fingerprint=snapshot.context_fingerprint,
            feature_payload=snapshot.feature_payload,
            risk_payload=snapshot.risk_payload,
            recommendation_payload=snapshot.recommendation_payload,
        )
        record.save()
        return snapshot

    def find_by_fingerprint(self, operation_id: str, context_fingerprint: str) -> Optional[IntelligenceSnapshot]:
        try:
            record = IntelligenceAssessmentRecord.objects.filter(
                operation_id=operation_id,
                context_fingerprint=context_fingerprint,
            ).first()
            if record is None:
                return None
            return self._to_domain(record)
        except Exception:
            return None

    def latest_for_operation(self, operation_id: str, organization_id: str) -> Optional[IntelligenceSnapshot]:
        record = IntelligenceAssessmentRecord.objects.filter(
            operation_id=operation_id,
            organization_id=organization_id,
        ).order_by("-assessed_at").first()
        if record is None:
            return None
        return self._to_domain(record)

    def history_for_operation(self, operation_id: str, organization_id: str) -> List[IntelligenceSnapshot]:
        records = IntelligenceAssessmentRecord.objects.filter(
            operation_id=operation_id,
            organization_id=organization_id,
        ).order_by("-assessed_at")
        return [self._to_domain(r) for r in records]

    def find_by_date_range(
        self,
        organization_id: str,
        start_date: datetime,
        end_date: datetime,
        actor,
    ) -> List[IntelligenceSnapshot]:
        from src.organizations.infrastructure.django.models import Membership
        from django.core.exceptions import PermissionDenied

        # Multi-tenant check
        if not getattr(actor, "is_superuser", False):
            has_access = Membership.objects.filter(
                user=actor,
                organization_id=organization_id,
                status="ACTIVE"
            ).exists()
            if not has_access:
                raise PermissionDenied("Acesso negado: ator não pertence à organização.")

        records = IntelligenceAssessmentRecord.objects.filter(
            organization_id=organization_id,
            assessed_at__range=(start_date, end_date),
        ).order_by("assessed_at")
        return [self._to_domain(r) for r in records]

    @staticmethod
    def _to_domain(record: IntelligenceAssessmentRecord) -> IntelligenceSnapshot:
        return IntelligenceSnapshot(
            id=str(record.id),
            organization_id=str(record.organization_id),
            operation_id=str(record.operation_id),
            assessed_at=record.assessed_at,
            reference_time=record.reference_time,
            risk_score=record.risk_score,
            risk_level=RiskLevel(record.risk_level),
            model_name=record.model_name,
            model_version=record.model_version,
            feature_schema_version=record.feature_schema_version,
            recommendation_policy_version=record.recommendation_policy_version,
            context_fingerprint=record.context_fingerprint,
            feature_payload=record.feature_payload,
            risk_payload=record.risk_payload,
            recommendation_payload=record.recommendation_payload,
        )
