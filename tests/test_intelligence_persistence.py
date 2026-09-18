import pytest
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.intelligence.domain.models import IntelligenceSnapshot
from src.intelligence.domain.enums import RiskLevel
from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
from src.intelligence.infrastructure.django.models import IntelligenceAssessmentRecord
from src.intelligence.application.serializers import IntelligencePayloadSerializer
from src.intelligence.domain.features import OperationFeatures
from src.intelligence.domain.models import RiskAssessment, Recommendation
from src.intelligence.domain.enums import RecommendationType


@pytest.fixture
def repo():
    return DjangoIntelligenceSnapshotRepository()


@pytest.fixture
def org_id():
    return str(uuid.uuid4())


@pytest.fixture
def org_id_b():
    return str(uuid.uuid4())


@pytest.fixture
def op_id():
    return str(uuid.uuid4())


def _make_snapshot(org_id, op_id, risk_score=0.35, risk_level=RiskLevel.MEDIUM, fingerprint=None):
    now = datetime.now(timezone.utc)
    return IntelligenceSnapshot(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        operation_id=op_id,
        assessed_at=now,
        reference_time=now,
        risk_score=risk_score,
        risk_level=risk_level,
        model_name="rule_based_operational_risk",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint=fingerprint or uuid.uuid4().hex + uuid.uuid4().hex[:32],
        feature_payload={"sla_overdue": True, "tracking_active": True, "total_stops": 2},
        risk_payload={"risk_score": risk_score, "risk_level": risk_level.value, "reasons": ["SLA atrasado"]},
        recommendation_payload=[{"type": "CONTACT_DRIVER", "priority": "HIGH"}],
    )


@pytest.mark.django_db
def test_save_snapshot(repo, org_id, op_id):
    snapshot = _make_snapshot(org_id, op_id)
    result = repo.save(snapshot)

    assert result.id == snapshot.id
    assert result.organization_id == org_id
    assert result.operation_id == op_id
    assert result.risk_score == 0.35
    assert result.risk_level == RiskLevel.MEDIUM

    # Verify persisted in database
    record = IntelligenceAssessmentRecord.objects.get(id=snapshot.id)
    assert str(record.operation_id) == op_id
    assert record.risk_level == "MEDIUM"
    assert record.feature_payload["sla_overdue"] is True


@pytest.mark.django_db
def test_immutable_history(repo, org_id, op_id):
    snapshot_a = _make_snapshot(org_id, op_id, risk_score=0.30, risk_level=RiskLevel.MEDIUM)
    snapshot_b = _make_snapshot(org_id, op_id, risk_score=0.65, risk_level=RiskLevel.HIGH)

    repo.save(snapshot_a)
    repo.save(snapshot_b)

    # Both records exist
    count = IntelligenceAssessmentRecord.objects.filter(operation_id=op_id).count()
    assert count == 2

    # Original snapshot unchanged
    record_a = IntelligenceAssessmentRecord.objects.get(id=snapshot_a.id)
    assert record_a.risk_score == 0.30


@pytest.mark.django_db
def test_versioning_preserved(repo, org_id, op_id):
    snapshot = _make_snapshot(org_id, op_id)
    repo.save(snapshot)

    record = IntelligenceAssessmentRecord.objects.get(id=snapshot.id)
    assert record.model_name == "rule_based_operational_risk"
    assert record.model_version == "1.0"
    assert record.feature_schema_version == "1.0"
    assert record.recommendation_policy_version == "1.0"


@pytest.mark.django_db
def test_tenant_isolation(repo, org_id, org_id_b, op_id):
    snapshot_a = _make_snapshot(org_id, op_id)
    repo.save(snapshot_a)

    # Query with wrong organization returns nothing
    result = repo.latest_for_operation(op_id, org_id_b)
    assert result is None

    history = repo.history_for_operation(op_id, org_id_b)
    assert len(history) == 0


@pytest.mark.django_db
def test_latest_for_operation(repo, org_id, op_id):
    now = datetime.now(timezone.utc)

    snapshot_old = _make_snapshot(org_id, op_id, risk_score=0.20, risk_level=RiskLevel.LOW)
    snapshot_old.assessed_at = now - timedelta(hours=1)

    snapshot_new = _make_snapshot(org_id, op_id, risk_score=0.70, risk_level=RiskLevel.HIGH)
    snapshot_new.assessed_at = now

    repo.save(snapshot_old)
    repo.save(snapshot_new)

    latest = repo.latest_for_operation(op_id, org_id)
    assert latest is not None
    assert latest.risk_score == 0.70
    assert latest.risk_level == RiskLevel.HIGH


@pytest.mark.django_db
def test_history_ordering(repo, org_id, op_id):
    now = datetime.now(timezone.utc)

    for i in range(3):
        snap = _make_snapshot(org_id, op_id, risk_score=0.1 * (i + 1))
        snap.assessed_at = now - timedelta(hours=2 - i)
        repo.save(snap)

    history = repo.history_for_operation(op_id, org_id)
    assert len(history) == 3
    # Most recent first (descending)
    assert history[0].assessed_at >= history[1].assessed_at
    assert history[1].assessed_at >= history[2].assessed_at


@pytest.mark.django_db
def test_idempotency_by_fingerprint(repo, org_id, op_id):
    fingerprint = "a" * 64
    snapshot = _make_snapshot(org_id, op_id, fingerprint=fingerprint)
    repo.save(snapshot)

    # find_by_fingerprint returns existing
    found = repo.find_by_fingerprint(op_id, fingerprint)
    assert found is not None
    assert found.id == snapshot.id

    # Different fingerprint returns None
    not_found = repo.find_by_fingerprint(op_id, "b" * 64)
    assert not_found is None


@pytest.mark.django_db
def test_snapshot_immutability_after_external_change(repo, org_id, op_id):
    snapshot = _make_snapshot(org_id, op_id, risk_score=0.40, risk_level=RiskLevel.MEDIUM)
    snapshot.feature_payload = {"sla_overdue": False, "tracking_active": True}
    repo.save(snapshot)

    # Simulate "external changes" by modifying the original object
    snapshot.feature_payload["sla_overdue"] = True

    # The persisted record should remain unchanged
    record = IntelligenceAssessmentRecord.objects.get(id=snapshot.id)
    assert record.feature_payload["sla_overdue"] is False


@pytest.mark.django_db
def test_serialization_roundtrip():
    features = OperationFeatures(
        operation_id="op-test",
        feature_schema_version="1.0",
        remaining_distance_km=123.456789,
        sla_margin_min=45.5,
        sla_overdue=False,
        tracking_active=True,
        has_thermal_requirement=True,
        temperature_below_min=None,
        total_weight_kg=1500.0,
    )

    payload = IntelligencePayloadSerializer.serialize_features(features)

    # float precision
    assert payload["remaining_distance_km"] == round(123.456789, 6)
    # None preserved
    assert payload["temperature_below_min"] is None
    # bool preserved
    assert payload["sla_overdue"] is False
    assert payload["tracking_active"] is True


@pytest.mark.django_db
def test_serialization_risk_roundtrip():
    now = datetime.now(timezone.utc)
    assessment = RiskAssessment(
        operation_id="op-test",
        risk_score=0.45,
        risk_level=RiskLevel.MEDIUM,
        reasons=["SLA baixo"],
        contributing_features=["sla_margin_min"],
        recommended_actions=["MONITOR"],
        model_name="rule_based_operational_risk",
        model_version="1.0",
        feature_schema_version="1.0",
        prediction_timestamp=now,
    )

    payload = IntelligencePayloadSerializer.serialize_risk(assessment)

    assert payload["risk_level"] == "MEDIUM"  # Enum serialized to value
    assert payload["prediction_timestamp"] == now.isoformat()
    assert payload["risk_score"] == 0.45


@pytest.mark.django_db
def test_serialization_recommendations_roundtrip():
    recs = [
        Recommendation(
            operation_id="op-test",
            type=RecommendationType.CONTACT_DRIVER,
            priority="HIGH",
            reason="SLA atrasado",
            suggested_action="Ligar para motorista",
            confidence=0.9,
            reason_code="SLA_OVERDUE",
            source_risk_codes=["SLA_OVERDUE"],
        )
    ]

    payload = IntelligencePayloadSerializer.serialize_recommendations(recs)

    assert len(payload) == 1
    assert payload[0]["type"] == "CONTACT_DRIVER"  # Enum serialized to value
    assert payload[0]["confidence"] == 0.9


@pytest.mark.django_db
def test_fingerprint_determinism():
    features = OperationFeatures(
        operation_id="op-test",
        feature_schema_version="1.0",
        sla_overdue=True,
        tracking_active=False,
    )

    payload = IntelligencePayloadSerializer.serialize_features(features)
    fp1 = IntelligencePayloadSerializer.compute_fingerprint(payload, "1.0", "1.0")
    fp2 = IntelligencePayloadSerializer.compute_fingerprint(payload, "1.0", "1.0")

    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex digest


@pytest.mark.django_db
def test_fingerprint_changes_with_different_features():
    features_a = OperationFeatures(operation_id="op-test", feature_schema_version="1.0", sla_overdue=True)
    features_b = OperationFeatures(operation_id="op-test", feature_schema_version="1.0", sla_overdue=False)

    payload_a = IntelligencePayloadSerializer.serialize_features(features_a)
    payload_b = IntelligencePayloadSerializer.serialize_features(features_b)

    fp_a = IntelligencePayloadSerializer.compute_fingerprint(payload_a, "1.0", "1.0")
    fp_b = IntelligencePayloadSerializer.compute_fingerprint(payload_b, "1.0", "1.0")

    assert fp_a != fp_b
