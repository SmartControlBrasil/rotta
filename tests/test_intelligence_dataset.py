import pytest
import uuid
from datetime import datetime, timezone, timedelta
from django.core.exceptions import PermissionDenied

from src.intelligence.domain.models import (
    OperationResultContext,
    DatasetRecord,
    OperationalOutcome,
    IntelligenceSnapshot,
)
from src.intelligence.domain.enums import RiskLevel
from src.intelligence.application.outcome_services import BuildOperationalOutcomeService
from src.intelligence.application.dataset_services import BuildOperationalRiskDatasetService
from src.intelligence.infrastructure.django.query_services import DjangoOperationResultContextQueryService
from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
from src.intelligence.infrastructure.django.models import IntelligenceAssessmentRecord
from tests.test_intelligence_architecture import org_a, user_a, user_b, driver_a, base_op_for_intel


@pytest.fixture
def outcome_service():
    return BuildOperationalOutcomeService()


@pytest.fixture
def base_result_context():
    return OperationResultContext(
        operation_id="op-123",
        organization_id="org-123",
        status="DELIVERED",
        assigned_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 24, 15, 0, 0, tzinfo=timezone.utc),
        delay_minutes=None,
        planned_deadline=datetime(2026, 8, 24, 16, 0, 0, tzinfo=timezone.utc),
        has_thermal_requirement=True,
        excursion_count=0,
        critical_incident_count=0,
        total_incident_count=0,
        all_delivery_stops_completed=True,
        all_delivery_stops_have_pod=True,
    )


# --- 1. Outcome Calculation Tests ---

def test_outcome_delivered_on_time(outcome_service, base_result_context):
    outcome = outcome_service.build_outcome(base_result_context)
    assert outcome.delivered_on_time is True
    assert outcome.delay_minutes == -60  # Completed 1h before deadline
    assert outcome.sla_breached is False
    assert outcome.operation_cancelled is False
    assert outcome.thermal_excursion_occurred is False
    assert outcome.critical_incident_occurred is False


def test_outcome_late_delivery(outcome_service, base_result_context):
    base_result_context.completed_at = datetime(2026, 8, 24, 17, 30, 0, tzinfo=timezone.utc)
    outcome = outcome_service.build_outcome(base_result_context)
    assert outcome.delivered_on_time is False
    assert outcome.delay_minutes == 90  # 1h30m late
    assert outcome.sla_breached is True
    assert outcome.operation_cancelled is False


def test_outcome_cancelled_operation(outcome_service, base_result_context):
    base_result_context.status = "CANCELLED"
    base_result_context.completed_at = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    outcome = outcome_service.build_outcome(base_result_context)
    assert outcome.delivered_on_time is None
    assert outcome.sla_breached is True
    assert outcome.operation_cancelled is True


def test_outcome_thermal_excursion(outcome_service, base_result_context):
    # With requirement and excursion
    base_result_context.excursion_count = 2
    outcome = outcome_service.build_outcome(base_result_context)
    assert outcome.thermal_excursion_occurred is True

    # Without thermal requirement
    base_result_context.has_thermal_requirement = False
    outcome = outcome_service.build_outcome(base_result_context)
    assert outcome.thermal_excursion_occurred is None


def test_outcome_incidents(outcome_service, base_result_context):
    base_result_context.critical_incident_count = 1
    outcome = outcome_service.build_outcome(base_result_context)
    assert outcome.critical_incident_occurred is True


# --- 2. Dataset Records & Separation Tests ---

@pytest.fixture
def mock_repo():
    class MockRepo:
        def __init__(self):
            self.snapshots = []
        def find_by_date_range(self, organization_id, start_date, end_date, actor):
            if actor == "unauthorized":
                raise PermissionDenied("Acesso negado")
            return [s for s in self.snapshots if s.organization_id == organization_id]
    return MockRepo()


@pytest.fixture
def mock_port():
    class MockPort:
        def __init__(self):
            self.contexts = {}
        def get_result_context(self, operation_id, actor):
            if actor == "unauthorized":
                raise PermissionDenied("Acesso negado")
            if operation_id not in self.contexts:
                raise ValueError("Not found")
            return self.contexts[operation_id]
    return MockPort()


def test_dataset_record_build_and_label_separation(mock_repo, mock_port, base_result_context):
    snap = IntelligenceSnapshot(
        id="snap-1",
        organization_id="org-123",
        operation_id="op-123",
        assessed_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
        reference_time=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
        risk_score=0.4,
        risk_level=RiskLevel.MEDIUM,
        model_name="rules",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="abc",
        feature_payload={"total_stops": 3, "sla_overdue": False},
        risk_payload={},
        recommendation_payload=[],
    )
    mock_repo.snapshots.append(snap)
    mock_port.contexts["op-123"] = base_result_context

    service = BuildOperationalRiskDatasetService(mock_repo, mock_port)
    records = service.build_dataset("org-123", "actor-ok", datetime.min, datetime.max)

    assert len(records) == 1
    rec = records[0]
    assert rec.snapshot_id == "snap-1"
    assert rec.eligibility == "COMPLETE"

    # Feature vs Label separation
    assert "total_stops" in rec.features
    assert "delivered_on_time" in rec.labels
    assert "total_stops" not in rec.labels
    assert "delivered_on_time" not in rec.features


def test_dataset_determinism_and_sorting(mock_repo, mock_port, base_result_context):
    # Two snapshots: snap2 at 12:00, snap1 at 10:00. Sorting should put snap1 first.
    snap1 = IntelligenceSnapshot(
        id="snap-1",
        organization_id="org-123",
        operation_id="op-123",
        assessed_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        reference_time=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        risk_score=0.2,
        risk_level=RiskLevel.LOW,
        model_name="rules",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="fp1",
        feature_payload={"total_stops": 2},
        risk_payload={},
        recommendation_payload=[],
    )
    snap2 = IntelligenceSnapshot(
        id="snap-2",
        organization_id="org-123",
        operation_id="op-123",
        assessed_at=datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc),
        reference_time=datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc),
        risk_score=0.8,
        risk_level=RiskLevel.CRITICAL,
        model_name="rules",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="fp2",
        feature_payload={"total_stops": 2},
        risk_payload={},
        recommendation_payload=[],
    )

    mock_repo.snapshots.append(snap2)  # Added out of order
    mock_repo.snapshots.append(snap1)
    mock_port.contexts["op-123"] = base_result_context

    service = BuildOperationalRiskDatasetService(mock_repo, mock_port)
    records = service.build_dataset("org-123", "actor-ok", datetime.min, datetime.max)

    assert len(records) == 2
    assert records[0].snapshot_id == "snap-1"
    assert records[1].snapshot_id == "snap-2"


def test_dataset_quality_report(mock_repo, mock_port, base_result_context):
    snap1 = IntelligenceSnapshot(
        id="snap-1",
        organization_id="org-123",
        operation_id="op-123",
        assessed_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        reference_time=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        risk_score=0.2,
        risk_level=RiskLevel.LOW,
        model_name="rules",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="fp1",
        feature_payload={"total_stops": 2, "tracking_active": False},  # No tracking
        risk_payload={},
        recommendation_payload=[],
    )
    mock_repo.snapshots.append(snap1)
    mock_port.contexts["op-123"] = base_result_context

    service = BuildOperationalRiskDatasetService(mock_repo, mock_port)
    records = service.build_dataset("org-123", "actor-ok", datetime.min, datetime.max)
    report = service.generate_quality_report(records)

    assert report.total_records == 1
    assert report.complete_records == 1
    assert report.missing_tracking_rate == 1.0  # tracking_active is False
    assert report.records_with_sla_label == 1


# --- 3. Integration & Django Database Tests ---

@pytest.mark.django_db
def test_integration_dataset_builder_pipeline_success(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    # 1. Create a Snapshot in Database
    now = datetime.now(timezone.utc)
    record = IntelligenceAssessmentRecord.objects.create(
        id=uuid.uuid4(),
        organization_id=base_op_for_intel.organization.id,
        operation_id=base_op_for_intel.id,
        assessed_at=now - timedelta(hours=2),
        reference_time=now - timedelta(hours=2),
        risk_score=0.1,
        risk_level="LOW",
        model_name="rule_based_operational_risk",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="test-fingerprint-123",
        feature_payload={"sla_overdue": False, "tracking_active": True, "tracking_point_count": 5},
        risk_payload={},
        recommendation_payload=[],
    )

    # 2. Build dataset using real services
    repo = DjangoIntelligenceSnapshotRepository()
    port = DjangoOperationResultContextQueryService()
    builder = BuildOperationalRiskDatasetService(repo, port)

    records = builder.build_dataset(
        organization_id=str(base_op_for_intel.organization.id),
        actor=user_a,
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=1),
    )

    assert len(records) == 1
    rec = records[0]
    assert rec.snapshot_id == str(record.id)
    assert rec.features["tracking_active"] is True
    # The operation is in status ASSIGNED (not terminal), so eligibility should be PARTIAL
    assert rec.eligibility == "PARTIAL"


@pytest.mark.django_db
def test_integration_dataset_builder_tenant_isolation(base_op_for_intel, user_b):
    # user_b does not belong to base_op_for_intel organization
    repo = DjangoIntelligenceSnapshotRepository()
    port = DjangoOperationResultContextQueryService()
    builder = BuildOperationalRiskDatasetService(repo, port)

    now = datetime.now(timezone.utc)

    # Calling dataset builder for user_b raises PermissionDenied
    with pytest.raises(PermissionDenied):
        builder.build_dataset(
            organization_id=str(base_op_for_intel.organization.id),
            actor=user_b,
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )


@pytest.mark.django_db
def test_label_leakage_protection(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    # 1. Capture snapshot at T1 (before completion/incidents)
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(hours=3)
    record = IntelligenceAssessmentRecord.objects.create(
        id=uuid.uuid4(),
        organization_id=base_op_for_intel.organization.id,
        operation_id=base_op_for_intel.id,
        assessed_at=t1,
        reference_time=t1,
        risk_score=0.0,
        risk_level="LOW",
        model_name="rule_based_operational_risk",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="leakage-test-fingerprint",
        feature_payload={"sla_overdue": False, "incident_count": 0, "completed_stops": 0},
        risk_payload={},
        recommendation_payload=[],
    )

    # 2. Modify operation in database (simulate time passing to Tn: stop completed, delay set)
    base_op_for_intel.status = "DELIVERED"
    base_op_for_intel.delay_minutes = 45
    base_op_for_intel.completed_at = now
    base_op_for_intel.save()

    # 3. Retrieve dataset record
    repo = DjangoIntelligenceSnapshotRepository()
    port = DjangoOperationResultContextQueryService()
    builder = BuildOperationalRiskDatasetService(repo, port)

    records = builder.build_dataset(
        organization_id=str(base_op_for_intel.organization.id),
        actor=user_a,
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=1),
    )

    assert len(records) == 1
    rec = records[0]

    # Leakage Assertion: Features represent T1 (0 completed stops, sla_overdue=False)
    assert rec.features["sla_overdue"] is False
    assert rec.features["incident_count"] == 0

    # Labels represent Tn (delay_minutes=45, sla_breached=True, eligibility=COMPLETE)
    assert rec.labels["delay_minutes"] == 45
    assert rec.labels["sla_breached"] is True
    assert rec.eligibility == "COMPLETE"
