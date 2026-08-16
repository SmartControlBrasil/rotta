import pytest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.domain.enums import TrackingSessionStatus, OperationStatus
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestCargo,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    TrackingSession,
    LocationPoint,
)
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer
from src.audit.infrastructure.django.models import AuditLog

from src.freights.application.tracking_services import (
    start_tracking_session,
    record_location_point,
    end_tracking_session,
)


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization, status="ACTIVE")
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())


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


def make_operation(organization, user, ref):
    import hashlib
    ref_hash = str(int(hashlib.md5(ref.encode('utf-8')).hexdigest(), 16))[:10]
    customer = Customer.objects.create(
        organization=organization,
        legal_name=f"Customer-{ref}",
        document_number=f"12{ref_hash}",
        email=f"customer-{ref}@example.com",
    )
    request = FreightRequest.objects.create(
        organization=organization,
        customer=customer,
        created_by=user,
        owner=user,
        reference_code=f"REQ-{ref}",
        status=FreightRequestStatus_ready_status(ref),
    )
    quote = FreightQuote.objects.create(
        organization=organization,
        freight_request=request,
        created_by=user,
        owner=user,
        reference_code=f"QT-{ref}",
    )
    offer = FreightOffer.objects.create(
        organization=organization,
        freight_request=request,
        freight_quote=quote,
        created_by=user,
        owner=user,
        reference_code=f"OFR-{ref}",
    )
    carrier, _ = CarrierProfile.objects.get_or_create(
        organization=organization,
        tenant=organization,
        defaults={
            "trade_name": f"Carrier-{ref}",
            "status": "ACTIVE",
            "email": f"carrier-{ref}@example.com",
        }
    )
    driver = Driver.objects.create(organization=organization, full_name=f"Driver-{ref}")
    vehicle = Vehicle.objects.create(organization=organization, plate=f"PLT{ref}", vehicle_type="CAR")
    interest = FreightOfferInterest.objects.create(
        organization=organization,
        offer=offer,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status="CONFIRMED",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest,
        organization=organization,
        offer=offer,
        status="CONFIRMED",
        selected_by=user,
        selected_at=timezone.now(),
    )
    operation = FreightOperation.objects.create(
        organization=organization,
        selection=selection,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status=OperationStatus.ASSIGNED.value,
        assigned_at=timezone.now(),
    )
    return operation


def FreightRequestStatus_ready_status(ref):
    # Just a helper to avoid hardcoded status values
    from src.freights.domain.enums import FreightRequestStatus
    return FreightRequestStatus.SUBMITTED.value


@pytest.mark.django_db(transaction=True)
def test_start_tracking_session_valid(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")

    session = start_tracking_session(user_a, op.id, source="mobile")
    assert session.status == TrackingSessionStatus.ACTIVE.value
    assert session.operation == op
    assert session.organization == org_a
    assert session.driver == op.driver
    assert session.vehicle == op.vehicle
    assert session.source == "mobile"

    # Verify AuditLog created
    audit = AuditLog.objects.filter(target_id=str(session.id), action="tracking_session_started").first()
    assert audit is not None
    # Ensure coordinates/GPS data is NOT in audit log
    if audit.metadata:
        assert "latitude" not in audit.metadata
        assert "longitude" not in audit.metadata


@pytest.mark.django_db
def test_start_tracking_session_duplicate_idempotence(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")

    session1 = start_tracking_session(user_a, op.id)
    session2 = start_tracking_session(user_a, op.id)

    assert session1.id == session2.id
    assert TrackingSession.objects.filter(operation=op, status=TrackingSessionStatus.ACTIVE.value).count() == 1


@pytest.mark.django_db
def test_start_tracking_session_no_permission(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.VIEWER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")

    with pytest.raises(PermissionDenied):
        start_tracking_session(user_a, op.id)


@pytest.mark.django_db
def test_start_tracking_session_wrong_org_scoping(org_a, org_b, user_a, user_b, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    grant(user_b, org_b, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    op_a = make_operation(org_a, user_a, "A")

    # user_b should not access or start tracking for user_a's operation
    with pytest.raises(PermissionDenied):
        start_tracking_session(user_b, op_a.id)


@pytest.mark.django_db
def test_record_location_point_valid(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")
    session = start_tracking_session(user_a, op.id)

    point = record_location_point(
        actor=user_a,
        tracking_session_id=session.id,
        latitude=Decimal("-23.550520"),
        longitude=Decimal("-46.633308"),
        accuracy_m=Decimal("5.0"),
        speed_kph=Decimal("60.0"),
        heading_deg=Decimal("180.0"),
        altitude_m=Decimal("750.0"),
        recorded_at=timezone.now(),
        sequence=1,
    )

    assert point.tracking_session == session
    assert point.operation == op
    assert point.driver == op.driver
    assert point.latitude == Decimal("-23.550520")
    assert point.longitude == Decimal("-46.633308")
    assert point.accuracy_m == Decimal("5.0")
    assert point.speed_kph == Decimal("60.0")
    assert point.heading_deg == Decimal("180.0")
    assert point.altitude_m == Decimal("750.0")
    assert point.sequence == 1


@pytest.mark.django_db
def test_record_location_point_invalid_geographic_values(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")
    session = start_tracking_session(user_a, op.id)

    # Invalid latitude
    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=91, longitude=0, accuracy_m=1)

    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=-91, longitude=0, accuracy_m=1)

    # Invalid longitude
    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=181, accuracy_m=1)

    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=-181, accuracy_m=1)

    # Invalid accuracy
    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=-1)

    # Invalid speed
    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=1, speed_kph=-5)

    # Invalid heading
    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=1, heading_deg=-1)

    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=1, heading_deg=360)


@pytest.mark.django_db
def test_record_location_point_session_ended_rejection(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")
    session = start_tracking_session(user_a, op.id)
    end_tracking_session(user_a, session.id)

    # Point should be rejected if session is not ACTIVE
    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=1)


@pytest.mark.django_db
def test_record_location_point_operation_delivered_or_cancelled_rejection(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")
    session = start_tracking_session(user_a, op.id)

    # Change status to DELIVERED
    op.status = OperationStatus.DELIVERED.value
    op.save()

    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=1)

    # Change status to CANCELLED
    op.status = OperationStatus.CANCELLED.value
    op.save()

    with pytest.raises(ValidationError):
        record_location_point(user_a, session.id, latitude=0, longitude=0, accuracy_m=1)


@pytest.mark.django_db
def test_record_location_point_idempotency(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")
    session = start_tracking_session(user_a, op.id)

    point1 = record_location_point(
        actor=user_a,
        tracking_session_id=session.id,
        latitude=Decimal("12"),
        longitude=Decimal("34"),
        accuracy_m=Decimal("5"),
        sequence=10,
        client_event_id="evt-123",
    )

    # Duplicate sequence / client_event_id should return same object
    point2 = record_location_point(
        actor=user_a,
        tracking_session_id=session.id,
        latitude=Decimal("12"),
        longitude=Decimal("34"),
        accuracy_m=Decimal("5"),
        sequence=10,
        client_event_id="evt-123",
    )

    assert point1.id == point2.id
    assert LocationPoint.objects.filter(tracking_session=session).count() == 1


@pytest.mark.django_db(transaction=True)
def test_end_tracking_session_valid(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")
    session = start_tracking_session(user_a, op.id)

    ended = end_tracking_session(user_a, session.id)
    assert ended.status == TrackingSessionStatus.ENDED.value
    assert ended.ended_at is not None

    # End is idempotent
    ended2 = end_tracking_session(user_a, session.id)
    assert ended.id == ended2.id

    # Verify AuditLog created
    audit = AuditLog.objects.filter(target_id=str(session.id), action="tracking_session_ended").first()
    assert audit is not None


@pytest.mark.django_db
def test_system_admin_bypass(org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.SYSTEM_ADMIN.value, AccessScope.ALL.value)
    op = make_operation(org_a, user_a, "A")

    session = start_tracking_session(user_a, op.id)
    assert session.status == TrackingSessionStatus.ACTIVE.value
