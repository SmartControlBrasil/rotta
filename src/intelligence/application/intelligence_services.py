import uuid
from datetime import datetime, timezone
from typing import Optional

from src.intelligence.domain.models import IntelligenceSnapshot, OperationContext
from src.intelligence.domain.features import OperationFeatures
from src.intelligence.application.ports import RiskModelPort, IntelligenceSnapshotRepositoryPort
from src.intelligence.application.feature_services import OperationalFeatureExtractor
from src.intelligence.application.recommendation_services import OperationalRecommendationEngine
from src.intelligence.application.serializers import IntelligencePayloadSerializer


RECOMMENDATION_POLICY_VERSION = "1.0"


class AssessOperationIntelligenceService:
    """Orchestrates the full intelligence pipeline and persists an immutable snapshot.

    Pipeline:
        OperationContext
        -> OperationalFeatureExtractor -> OperationFeatures
        -> RiskModelPort -> RiskAssessment
        -> OperationalRecommendationEngine -> Recommendation[]
        -> Serialize & Fingerprint
        -> Idempotency check
        -> Persist IntelligenceSnapshot
    """

    def __init__(
        self,
        risk_model: RiskModelPort,
        snapshot_repository: IntelligenceSnapshotRepositoryPort,
    ):
        self._risk_model = risk_model
        self._snapshot_repository = snapshot_repository
        self._extractor = OperationalFeatureExtractor()
        self._recommender = OperationalRecommendationEngine()
        self._serializer = IntelligencePayloadSerializer

    def assess(
        self,
        context: OperationContext,
        reference_time: Optional[datetime] = None,
    ) -> IntelligenceSnapshot:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        # 1. Extract features
        features = self._extractor.extract(context, reference_time=reference_time)

        # 2. Risk assessment
        assessment = self._risk_model.predict(features)

        # 3. Recommendations
        recommendations = self._recommender.recommend(features, assessment)

        # 4. Serialize payloads
        feature_payload = self._serializer.serialize_features(features)
        risk_payload = self._serializer.serialize_risk(assessment)
        recommendation_payload = self._serializer.serialize_recommendations(recommendations)

        # 5. Compute fingerprint
        context_fingerprint = self._serializer.compute_fingerprint(
            feature_payload,
            assessment.model_version,
            features.feature_schema_version,
        )

        # 6. Idempotency check
        existing = self._snapshot_repository.find_by_fingerprint(
            operation_id=context.operation_id,
            context_fingerprint=context_fingerprint,
        )
        if existing is not None:
            return existing

        # 7. Build snapshot
        snapshot = IntelligenceSnapshot(
            id=str(uuid.uuid4()),
            organization_id=context.organization_id,
            operation_id=context.operation_id,
            assessed_at=datetime.now(timezone.utc),
            reference_time=reference_time,
            risk_score=assessment.risk_score,
            risk_level=assessment.risk_level,
            model_name=assessment.model_name,
            model_version=assessment.model_version,
            feature_schema_version=features.feature_schema_version,
            recommendation_policy_version=RECOMMENDATION_POLICY_VERSION,
            context_fingerprint=context_fingerprint,
            feature_payload=feature_payload,
            risk_payload=risk_payload,
            recommendation_payload=recommendation_payload,
        )

        # 8. Persist (atomic — failure here fails the entire assessment)
        return self._snapshot_repository.save(snapshot)
