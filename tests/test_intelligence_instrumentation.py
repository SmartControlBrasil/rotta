import pytest
import uuid
from datetime import datetime, timezone, timedelta

from src.intelligence.domain.models import (
    IntelligenceSnapshot,
    DatasetRecord,
    OperationContext,
)
from src.intelligence.domain.features import OperationFeatures
from src.intelligence.domain.enums import RiskLevel
from src.intelligence.application.sampling_services import OperationalIntelligenceSamplingPolicyV1
from src.intelligence.application.collection_services import CollectOperationIntelligenceService
from src.intelligence.application.evaluation_services import EvaluateRuleBasedBaselineService
from src.intelligence.application.ports import RiskModelPort, IntelligenceSnapshotRepositoryPort
from src.intelligence.application.intelligence_services import AssessOperationIntelligenceService
from tests.test_intelligence_architecture import org_a, user_a, user_b, driver_a, base_op_for_intel


@pytest.fixture
def sampling_policy():
    return OperationalIntelligenceSamplingPolicyV1(debounce_minutes=15)


@pytest.fixture
def mock_snapshot():
    now = datetime.now(timezone.utc)
    return IntelligenceSnapshot(
        id="snap-1",
        organization_id="org-123",
        operation_id="op-123",
        assessed_at=now - timedelta(minutes=10),
        reference_time=now - timedelta(minutes=10),
        risk_score=0.2,
        risk_level=RiskLevel.LOW,
        model_name="rules",
        model_version="1.0",
        feature_schema_version="1.0",
        recommendation_policy_version="1.0",
        context_fingerprint="fp1",
        feature_payload={
            "incident_count": 0,
            "thermal_excursion_count": 0,
            "sla_overdue": False,
            "completed_stops": 0,
        },
        risk_payload={},
        recommendation_payload=[],
    )


@pytest.fixture
def current_features():
    return OperationFeatures(
        operation_id="op-123",
        feature_schema_version="1.0",
        incident_count=0,
        thermal_excursion_count=0,
        sla_overdue=False,
        completed_stops=0,
    )


# --- 1. Sampling Policy Tests ---

def test_sampling_policy_first_snapshot(sampling_policy, current_features):
    # If no previous snapshot exists, always assess
    assert sampling_policy.should_assess(current_features, None, "GPS_UPDATED") is True


def test_sampling_policy_debounce_active(sampling_policy, current_features, mock_snapshot):
    # Only 10 minutes elapsed, no features changed -> should skip assessment (return False)
    assert sampling_policy.should_assess(current_features, mock_snapshot, "GPS_UPDATED") is False


def test_sampling_policy_debounce_expired(sampling_policy, current_features, mock_snapshot):
    # Change assessed_at to 20 minutes ago -> should assess (return True)
    mock_snapshot.assessed_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert sampling_policy.should_assess(current_features, mock_snapshot, "GPS_UPDATED") is True


def test_sampling_policy_critical_event_bypass(sampling_policy, current_features, mock_snapshot):
    # Within debounce window, but critical event -> should bypass debounce and assess
    assert sampling_policy.should_assess(current_features, mock_snapshot, "INCIDENT_REPORTED") is True
    assert sampling_policy.should_assess(current_features, mock_snapshot, "POD_CREATED") is True


def test_sampling_policy_significant_change_bypass(sampling_policy, current_features, mock_snapshot):
    # Within debounce window, but significant feature change -> should assess

    # 1. Incident count changed
    current_features.incident_count = 1
    assert sampling_policy.should_assess(current_features, mock_snapshot, "GPS_UPDATED") is True
    current_features.incident_count = 0

    # 2. Thermal excursion occurred
    current_features.thermal_excursion_count = 1
    assert sampling_policy.should_assess(current_features, mock_snapshot, "GPS_UPDATED") is True
    current_features.thermal_excursion_count = 0

    # 3. SLA overdue changed
    current_features.sla_overdue = True
    assert sampling_policy.should_assess(current_features, mock_snapshot, "GPS_UPDATED") is True


# --- 2. Failure Isolation Tests ---

def test_collection_failure_isolation():
    # Mock dependencies that fail
    class FailingAssessService:
        def assess(self, context, reference_time=None):
            raise RuntimeError("Database connection lost")

    class MockSnapshotRepo:
        def latest_for_operation(self, op_id, org_id):
            return None

    assess_service = FailingAssessService()
    repo = MockSnapshotRepo()

    # Instantiate CollectOperationIntelligenceService
    service = CollectOperationIntelligenceService(assess_service, repo)

    # Context to evaluate
    context = OperationContext(
        operation_id="op-123",
        organization_id="org-123",
        status="ASSIGNED",
        source_type="MARKETPLACE",
        carrier=None,
        driver=None,
        vehicle=None,
        stops=[],
        cargo_lots=[],
        sla=None,
        tracking=None,
        incidents=[],
        thermal=None,
        events=[],
    )

    # Triggering collection should handle the RuntimeError gracefully, log it, and return None
    # No exception must propagate to the caller.
    result = None
    try:
        result = service.collect(context, "OPERATION_CREATED")
    except Exception as e:
        pytest.fail(f"Exception should have been isolated, but raised: {str(e)}")

    assert result is None


# --- 3. Confusion Matrix and Metric Evaluation Tests ---

def test_confusion_matrix_calculations():
    evaluator = EvaluateRuleBasedBaselineService()

    # 1. Complete dataset containing:
    # SLA TP: predicted SLA risk = True, actual breach = True
    # SLA FP: predicted SLA risk = True, actual breach = False
    # SLA TN: predicted SLA risk = False, actual breach = False
    # SLA FN: predicted SLA risk = False, actual breach = True

    rec_tp = DatasetRecord(
        snapshot_id="1", operation_id="o1", organization_id="org", assessed_at=datetime.now(),
        feature_schema_version="1.0", model_name="rules", model_version="1.0",
        features={"sla_overdue": True}, labels={"sla_breached": True}, eligibility="COMPLETE", metadata={}
    )
    rec_fp = DatasetRecord(
        snapshot_id="2", operation_id="o2", organization_id="org", assessed_at=datetime.now(),
        feature_schema_version="1.0", model_name="rules", model_version="1.0",
        features={"sla_overdue": True}, labels={"sla_breached": False}, eligibility="COMPLETE", metadata={}
    )
    rec_tn = DatasetRecord(
        snapshot_id="3", operation_id="o3", organization_id="org", assessed_at=datetime.now(),
        feature_schema_version="1.0", model_name="rules", model_version="1.0",
        features={"sla_overdue": False, "has_sla": True, "sla_margin_min": 150}, labels={"sla_breached": False}, eligibility="COMPLETE", metadata={}
    )
    rec_fn = DatasetRecord(
        snapshot_id="4", operation_id="o4", organization_id="org", assessed_at=datetime.now(),
        feature_schema_version="1.0", model_name="rules", model_version="1.0",
        features={"sla_overdue": False, "has_sla": True, "sla_margin_min": 150}, labels={"sla_breached": True}, eligibility="COMPLETE", metadata={}
    )

    report = evaluator.evaluate([rec_tp, rec_fp, rec_tn, rec_fn])

    sla_eval = report.sla_evaluation
    assert sla_eval.tp == 1
    assert sla_eval.fp == 1
    assert sla_eval.tn == 1
    assert sla_eval.fn == 1

    assert sla_eval.precision == 0.5   # 1 / (1 + 1)
    assert sla_eval.recall == 0.5      # 1 / (1 + 1)
    assert sla_eval.specificity == 0.5 # 1 / (1 + 1)


def test_evaluator_handles_zero_division():
    evaluator = EvaluateRuleBasedBaselineService()

    # Empty dataset or no COMPLETE records
    report = evaluator.evaluate([])

    assert report.sla_evaluation.precision is None
    assert report.sla_evaluation.recall is None
    assert report.false_positive_rate == 0.0
    assert report.false_negative_rate == 0.0


# --- 4. Integration & Django Database CLI Tests ---

@pytest.mark.django_db
def test_cli_report_command_execution(base_op_for_intel, user_a):
    user_a.is_superuser = True
    user_a.save()
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    from io import StringIO
    from django.core.management import call_command

    out = StringIO()
    call_command(
        "intelligence_dataset_report",
        organization=str(base_op_for_intel.organization.id),
        stdout=out
    )
    output = out.getvalue()

    assert "AI Core Dataset Report" in output
    assert "Total Snapshots:" in output
    assert "Complete Records" in output
    assert "Baseline Rule Engine Evaluation" in output


# --- 5. Operational Intelligence Integration Tests ---

@pytest.mark.django_db
def test_operational_lifecycle_triggers_ai_assessment(base_op_for_intel, user_a, django_capture_on_commit_callbacks):
    user_a.is_superuser = True
    user_a.save()

    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    from src.freights.domain.enums import OperationStatus
    from src.freights.application.operation_services import (
        change_operation_status,
        report_operation_incident,
    )
    from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository

    repo = DjangoIntelligenceSnapshotRepository()

    # 1. Test change_operation_status
    with django_capture_on_commit_callbacks(execute=True):
        change_operation_status(
            operation_id=str(base_op_for_intel.id),
            new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
            actor=user_a,
        )

    # Verify snapshot was created
    snapshot = repo.latest_for_operation(str(base_op_for_intel.id), str(base_op_for_intel.organization.id))
    assert snapshot is not None
    assert snapshot.risk_level == RiskLevel.LOW

    # 2. Test report_operation_incident
    with django_capture_on_commit_callbacks(execute=True):
        report_operation_incident(
            operation_id=str(base_op_for_intel.id),
            description="Acidente grave na via principal",
            actor=user_a,
        )

    # Incident count features change -> risk score changes
    snapshot_after_incident = repo.latest_for_operation(str(base_op_for_intel.id), str(base_op_for_intel.organization.id))
    assert snapshot_after_incident is not None
    assert snapshot_after_incident.id != snapshot.id
    assert snapshot_after_incident.risk_score > snapshot.risk_score
    assert snapshot_after_incident.feature_payload.get("incident_count") == 1


@pytest.mark.django_db
def test_query_service_tenant_isolation(base_op_for_intel, user_a, user_b):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    # user_b is not part of the organization
    from src.intelligence.application.query_services import OperationIntelligenceQueryService
    from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository

    repo = DjangoIntelligenceSnapshotRepository()
    query_service = OperationIntelligenceQueryService(repo)

    # Assess operation first to have a snapshot
    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(base_op_for_intel.id),
        event_type="OPERATION_CREATED",
        actor=user_a,
    )

    # user_a can query successfully
    dto = query_service.get_latest_assessment(
        operation_id=str(base_op_for_intel.id),
        organization_id=str(base_op_for_intel.organization.id),
        actor=user_a,
    )
    assert dto.risk_level == "LOW"

    # user_b is denied access
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        query_service.get_latest_assessment(
            operation_id=str(base_op_for_intel.id),
            organization_id=str(base_op_for_intel.organization.id),
            actor=user_b,
        )


@pytest.mark.django_db
def test_query_service_neutral_state_when_no_snapshot(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    from src.intelligence.application.query_services import OperationIntelligenceQueryService
    from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository

    repo = DjangoIntelligenceSnapshotRepository()
    query_service = OperationIntelligenceQueryService(repo)

    # Do not create snapshot
    dto = query_service.get_latest_assessment(
        operation_id=str(base_op_for_intel.id),
        organization_id=str(base_op_for_intel.organization.id),
        actor=user_a,
    )
    assert dto.risk_level == "NOT_ASSESSED"
    assert dto.risk_score is None


@pytest.mark.django_db
def test_query_service_batch_performance_n1(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    from src.intelligence.application.query_services import OperationIntelligenceQueryService
    from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository

    repo = DjangoIntelligenceSnapshotRepository()
    query_service = OperationIntelligenceQueryService(repo)

    # Assess operation
    from src.intelligence.application.collection_services import CollectOperationIntelligenceService
    CollectOperationIntelligenceService.trigger_for_operation(
        operation_id=str(base_op_for_intel.id),
        event_type="OPERATION_CREATED",
        actor=user_a,
    )

    non_existent_uuid = str(uuid.uuid4())
    batch = query_service.get_latest_assessments_for_operations([str(base_op_for_intel.id), non_existent_uuid], user_a)
    assert len(batch) == 2
    assert batch[str(base_op_for_intel.id)].risk_level == "LOW"
    assert batch[non_existent_uuid].risk_level == "NOT_ASSESSED"


@pytest.mark.django_db
def test_failure_isolation(base_op_for_intel, user_a, django_capture_on_commit_callbacks, monkeypatch):
    user_a.is_superuser = True
    user_a.save()

    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    # Force the RuleBasedRiskModel to raise an error
    from src.intelligence.infrastructure.risk.rule_based_model import RuleBasedRiskModel
    def mock_predict(*args, **kwargs):
        raise RuntimeError("Risk Engine Failed!")
    monkeypatch.setattr(RuleBasedRiskModel, "predict", mock_predict)

    from src.freights.domain.enums import OperationStatus
    from src.freights.application.operation_services import change_operation_status

    # Usecase transaction must succeed despite AI failure
    with django_capture_on_commit_callbacks(execute=True):
        op = change_operation_status(
            operation_id=str(base_op_for_intel.id),
            new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
            actor=user_a,
        )

    # Core operation succeeded
    assert op.status == OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP.value
