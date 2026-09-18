import logging
from datetime import datetime, timezone
from typing import Optional

from src.intelligence.domain.models import OperationContext, IntelligenceSnapshot
from src.intelligence.application.ports import RiskModelPort, IntelligenceSnapshotRepositoryPort
from src.intelligence.application.intelligence_services import AssessOperationIntelligenceService
from src.intelligence.application.feature_services import OperationalFeatureExtractor
from src.intelligence.application.sampling_services import OperationalIntelligenceSamplingPolicyV1

logger = logging.getLogger(__name__)


class CollectOperationIntelligenceService:
    """Orchestrates event-driven collection using the sampling policy.

    Enforces failure isolation: intelligence failures will NOT crash the logistical pipeline.
    """

    def __init__(
        self,
        assess_service: AssessOperationIntelligenceService,
        snapshot_repository: IntelligenceSnapshotRepositoryPort,
    ):
        self._assess_service = assess_service
        self._snapshot_repository = snapshot_repository
        self._extractor = OperationalFeatureExtractor()
        self._sampling_policy = OperationalIntelligenceSamplingPolicyV1()

    def collect(
        self,
        context: OperationContext,
        event_type: str,
        reference_time: Optional[datetime] = None,
    ) -> Optional[IntelligenceSnapshot]:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        try:
            # 1. Extract features temporarily to run sampling policy
            features = self._extractor.extract(context, reference_time=reference_time)

            # 2. Get latest snapshot
            latest_snapshot = self._snapshot_repository.latest_for_operation(
                context.operation_id,
                context.organization_id
            )

            # 3. Check eligibility
            if self._sampling_policy.should_assess(
                features=features,
                latest_snapshot=latest_snapshot,
                event_type=event_type,
                reference_time=reference_time,
            ):
                # 4. Trigger assessment
                return self._assess_service.assess(context, reference_time=reference_time)

            return None

        except Exception as e:
            # FAILURE ISOLATION: Log failure but do not propagate. The original operation must continue.
            logger.error(
                "AI Collection failed for Operation %s | Event %s | Error: %s",
                context.operation_id,
                event_type,
                str(e),
                exc_info=True
            )
            return None

    @classmethod
    def trigger_for_operation(
        cls,
        operation_id: str,
        event_type: str,
        actor,
        reference_time: Optional[datetime] = None,
    ) -> Optional[IntelligenceSnapshot]:
        try:
            from src.intelligence.infrastructure.django.query_services import DjangoOperationContextQueryService
            from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
            from src.intelligence.infrastructure.risk.rule_based_model import RuleBasedRiskModel
            from src.intelligence.application.intelligence_services import AssessOperationIntelligenceService

            query_service = DjangoOperationContextQueryService()
            context = query_service.get_context(operation_id, actor)

            repo = DjangoIntelligenceSnapshotRepository()
            risk_model = RuleBasedRiskModel()
            assess_service = AssessOperationIntelligenceService(risk_model, repo)

            collector = cls(assess_service, repo)
            return collector.collect(context, event_type, reference_time=reference_time)
        except Exception as e:
            logger.error(
                "AI Collection Trigger failed for Operation %s | Event %s | Error: %s",
                operation_id,
                event_type,
                str(e),
                exc_info=True
            )
            return None
