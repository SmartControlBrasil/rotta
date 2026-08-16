import pytest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
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
    from src.freights.domain.enums import FreightRequestStatus
    return FreightRequestStatus.SUBMITTED.value


@pytest.mark.django_db
def test_backoffice_renders_tracking_telemetry_correctly(client, org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    op = make_operation(org_a, user_a, "A")

    session = TrackingSession.objects.create(
        organization=org_a,
        operation=op,
        driver=op.driver,
        vehicle=op.vehicle,
        started_at=timezone.now(),
        status=TrackingSessionStatus.ACTIVE.value,
    )
    
    point = LocationPoint.objects.create(
        organization=org_a,
        tracking_session=session,
        operation=op,
        driver=op.driver,
        latitude=Decimal("-23.550520"),
        longitude=Decimal("-46.633308"),
        accuracy_m=Decimal("5.20"),
        speed_kph=Decimal("45.50"),
        heading_deg=Decimal("90.0"),
        altitude_m=Decimal("800.00"),
        recorded_at=timezone.now(),
        sequence=1,
    )

    client.force_login(user_a)
    response = client.get(reverse("backoffice:freight_operation_detail", args=[op.id]), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()

    # Verify Rastreamento title
    assert "Rastreamento em Tempo Quase Real" in content
    
    # Session Details
    assert str(session.id)[:8] in content
    assert "ACTIVE" in content
    
    # GPS position & accuracy & speed textual assertions
    assert "-23" in content
    assert "-46" in content
    assert "5" in content
    assert "45" in content
    assert "90" in content
    assert "800" in content

    # Verify absolutely NO fake map references
    assert "iframe" not in content
    assert "leaflet" not in content.lower()
    assert "mapbox" not in content.lower()
    assert "google.com/maps" not in content.lower()


@pytest.mark.django_db
def test_backoffice_scoping_no_data_leakage(client, org_a, org_b, user_a, user_b, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    grant(user_b, org_b, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_b, "B")

    session_b = TrackingSession.objects.create(
        organization=org_b,
        operation=op_b,
        driver=op_b.driver,
        vehicle=op_b.vehicle,
        started_at=timezone.now(),
        status=TrackingSessionStatus.ACTIVE.value,
    )
    LocationPoint.objects.create(
        organization=org_b,
        tracking_session=session_b,
        operation=op_b,
        driver=op_b.driver,
        latitude=Decimal("-25.123456"),
        longitude=Decimal("-48.654321"),
        accuracy_m=Decimal("3.00"),
        recorded_at=timezone.now(),
    )

    client.force_login(user_a)
    
    # User A tries to get User B's operation detail - should be 404/denied due to operation scoping
    response = client.get(reverse("backoffice:freight_operation_detail", args=[op_b.id]), HTTP_HOST="localhost")
    assert response.status_code == 404
