import pytest
from decimal import Decimal
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization
from src.drivers.infrastructure.django.models import Driver
from src.intelligence.infrastructure.django.query_services import DjangoOperationContextQueryService
from src.intelligence.domain.enums import RiskLevel
from tests.test_api_v1_driver_operations import make_operation

@pytest.fixture
def org_a(db):
    return Organization.objects.create(
        name="Org A",
        type=OrganizationType.TRANSPORT_COMPANY,
    )

@pytest.fixture
def org_b(db):
    return Organization.objects.create(
        name="Org B",
        type=OrganizationType.TRANSPORT_COMPANY,
    )

@pytest.fixture
def user_a(db, django_user_model):
    return django_user_model.objects.create_user(username="usera", password="password")

@pytest.fixture
def user_b(db, django_user_model):
    return django_user_model.objects.create_user(username="userb", password="password")

@pytest.fixture
def driver_a(db, org_a, user_a):
    return Driver.objects.create(organization=org_a, user=user_a, full_name="Driver A")

@pytest.fixture
def base_op_for_intel(db, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "INTEL")

    # 1. Create related structures to populate contexts
    # Create a tracking session & location point
    from src.freights.infrastructure.django.models import TrackingSession, LocationPoint, ThermalReading, ThermalExcursion
    session = TrackingSession.objects.create(
        organization=org_a,
        operation=op,
        driver=driver_a,
        started_at=timezone.now(),
        status="ACTIVE"
    )
    LocationPoint.objects.create(
        organization=org_a,
        tracking_session=session,
        operation=op,
        driver=driver_a,
        latitude=Decimal("45.123456"),
        longitude=Decimal("-12.654321"),
        accuracy_m=Decimal("5.00"),
        recorded_at=timezone.now(),
        sequence=1,
    )

    # Create thermal readings and excursions
    ThermalReading.objects.create(
        operation=op,
        device_id="sensor-99",
        tracking_session=session,
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("5.50"),
    )
    ThermalExcursion.objects.create(
        operation=op,
        sensor_id="sensor-99",
        started_at=timezone.now(),
        direction="ABOVE_MAX",
        min_observed=Decimal("5.50"),
        max_observed=Decimal("8.50"),
    )

    from src.freights.infrastructure.django.models import FreightOperationCargoLot
    FreightOperationCargoLot.objects.create(
        operation=op,
        description="Test Lot",
        weight_kg=Decimal("100.00"),
        volume_m3=Decimal("2.00"),
        pickup_stop=op.stops.first(),
        delivery_stop=op.stops.last()
    )

    return op

@pytest.mark.django_db
def test_django_operation_context_query_service_success(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    service = DjangoOperationContextQueryService()
    ctx = service.get_context(base_op_for_intel.id, user_a)

    # Verify mapping
    assert ctx.operation_id == str(base_op_for_intel.id)
    assert ctx.organization_id == str(base_op_for_intel.organization_id)
    assert ctx.status == base_op_for_intel.status
    assert ctx.carrier is not None
    assert ctx.carrier.trade_name.startswith("Carrier")
    assert ctx.driver is not None
    assert ctx.driver.full_name == "Driver A"
    assert ctx.vehicle is not None
    assert ctx.vehicle.plate == "PLTINTEL"

    # Verify stops and cargo lots mapping
    assert len(ctx.stops) == 2
    assert ctx.stops[0].sequence == 1
    assert ctx.stops[0].stop_type == "PICKUP"
    assert ctx.stops[1].sequence == 2
    assert ctx.stops[1].stop_type == "DELIVERY"
    assert len(ctx.cargo_lots) == 1

    # Verify telemetry tracking
    assert ctx.tracking.has_active_session is True
    assert ctx.tracking.last_latitude == 45.123456
    assert ctx.tracking.last_longitude == -12.654321
    assert ctx.tracking.total_points == 1

    # Verify thermal telemetry
    assert ctx.thermal.last_reading == 5.50
    assert ctx.thermal.excursion_count == 1
    assert ctx.thermal.is_in_excursion is True

@pytest.mark.django_db
def test_django_operation_context_query_service_tenant_isolation(base_op_for_intel, user_b):
    # user_b does not belong to org_a
    service = DjangoOperationContextQueryService()

    with pytest.raises(PermissionDenied) as exc_info:
        service.get_context(base_op_for_intel.id, user_b)

    assert "Acesso negado" in str(exc_info.value)

@pytest.mark.django_db
def test_django_operation_context_query_service_superuser_bypass(base_op_for_intel, django_user_model):
    admin = django_user_model.objects.create_superuser(username="admin_intel", email="admin@rotta.com", password="pwd")
    service = DjangoOperationContextQueryService()

    # Superuser bypasses tenant checks
    ctx = service.get_context(base_op_for_intel.id, admin)
    assert ctx.operation_id == str(base_op_for_intel.id)


@pytest.mark.django_db
def test_integration_query_service_and_extractor(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    service = DjangoOperationContextQueryService()
    ctx = service.get_context(base_op_for_intel.id, user_a)

    from src.intelligence.application.feature_services import OperationalFeatureExtractor
    extractor = OperationalFeatureExtractor()
    features = extractor.extract(ctx)

    assert features.operation_id == str(base_op_for_intel.id)
    assert features.feature_schema_version == "1.0"
    assert features.total_stops == 2
    assert features.cargo_lot_count == 1
    assert features.total_weight_kg == 100.0
    assert features.total_volume_m3 == 2.0
    assert features.has_driver is True
    assert features.has_vehicle is True
    assert features.tracking_active is True
    assert features.tracking_point_count == 1
    assert features.thermal_excursion_count == 1


@pytest.mark.django_db
def test_integration_full_risk_assessment_pipeline(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    service = DjangoOperationContextQueryService()
    ctx = service.get_context(base_op_for_intel.id, user_a)

    from src.intelligence.application.feature_services import OperationalFeatureExtractor
    extractor = OperationalFeatureExtractor()
    features = extractor.extract(ctx)

    from src.intelligence.infrastructure.risk.rule_based_model import RuleBasedRiskModel
    model = RuleBasedRiskModel()
    assessment = model.predict(features)

    # Verify risk assessment pipeline outcome
    assert assessment.operation_id == str(base_op_for_intel.id)
    # The operation created in base_op_for_intel has:
    # - Thermal requirement: False (default from make_operation since no temperature limit is set there)
    # - Thermal excursion count: 1 (but has_thermal_requirement is False, so ignored)
    # - Tracking session: active (tracking_active = True)
    # - Driver and vehicle assigned (True)
    # - SLA status: ON_TIME
    # - Stops count: 2 (not multi-stop)
    # - Cargo lot count: 1 (not fractional)
    # So risk score should be 0.0 (Low risk) because all rules are healthy/untriggered!
    assert assessment.risk_score == 0.0
    assert assessment.risk_level == RiskLevel.LOW
    assert len(assessment.reasons) == 0
    assert assessment.model_name == "rule_based_operational_risk"
    assert assessment.model_version == "1.0"


@pytest.mark.django_db
def test_integration_recommendation_pipeline(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    service = DjangoOperationContextQueryService()
    ctx = service.get_context(base_op_for_intel.id, user_a)

    from src.intelligence.application.feature_services import OperationalFeatureExtractor
    extractor = OperationalFeatureExtractor()
    features = extractor.extract(ctx)

    from src.intelligence.infrastructure.risk.rule_based_model import RuleBasedRiskModel
    model = RuleBasedRiskModel()
    assessment = model.predict(features)

    from src.intelligence.application.recommendation_services import OperationalRecommendationEngine
    engine = OperationalRecommendationEngine()
    recommendations = engine.recommend(features, assessment)

    # Healthy operation has zero recommendations
    assert len(recommendations) == 0


@pytest.mark.django_db
def test_integration_full_pipeline_with_persistence(base_op_for_intel, user_a):
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.get_or_create(user=user_a, organization=base_op_for_intel.organization, defaults={"status": "ACTIVE"})

    service = DjangoOperationContextQueryService()
    ctx = service.get_context(base_op_for_intel.id, user_a)

    from datetime import datetime, timezone
    from src.intelligence.infrastructure.risk.rule_based_model import RuleBasedRiskModel
    from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
    from src.intelligence.application.intelligence_services import AssessOperationIntelligenceService

    risk_model = RuleBasedRiskModel()
    repository = DjangoIntelligenceSnapshotRepository()
    intel_service = AssessOperationIntelligenceService(risk_model, repository)

    # Use fixed reference_time for deterministic feature extraction
    fixed_ref_time = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    snapshot = intel_service.assess(ctx, reference_time=fixed_ref_time)

    # Verify snapshot was persisted
    assert snapshot.operation_id == str(base_op_for_intel.id)
    assert snapshot.organization_id == str(base_op_for_intel.organization.id)
    assert snapshot.risk_score == 0.0
    assert snapshot.risk_level == RiskLevel.LOW
    assert snapshot.model_name == "rule_based_operational_risk"
    assert snapshot.feature_payload is not None
    assert snapshot.risk_payload is not None
    assert snapshot.recommendation_payload is not None

    # Verify it's queryable from repository
    latest = repository.latest_for_operation(
        str(base_op_for_intel.id),
        str(base_op_for_intel.organization.id),
    )
    assert latest is not None
    assert latest.id == snapshot.id

    # Verify idempotency: same context + same reference_time = same snapshot (no duplicate)
    snapshot2 = intel_service.assess(ctx, reference_time=fixed_ref_time)
    assert snapshot2.id == snapshot.id
