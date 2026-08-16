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
from src.shared.interfaces.api.v1.auth import generate_signed_token


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
def user_a(db, django_user_model):
    return django_user_model.objects.create_user(username="usera", password="password")


@pytest.fixture
def driver_a(db, org_a, user_a):
    return Driver.objects.create(organization=org_a, user=user_a, full_name="Driver A")


def make_operation(organization, user, driver, ref):
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
        status="SUBMITTED",
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


@pytest.mark.django_db(transaction=True)
def test_tracking_lifecycle_flow(client, org_a, user_a, driver_a, rbac_ready):
    # Grant permissions so that tracking service calls pass the view's mobile decorator check
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    op = make_operation(org_a, user_a, driver_a, "A")
    token = generate_signed_token(user_a)

    # 1. Start tracking session
    start_url = reverse("api_v1:start_tracking", args=[op.id])
    response = client.post(
        start_url,
        data={"source": "mobile-app", "device_metadata": {"os": "iOS"}},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 201
    json_data = response.json()
    session_id = json_data["tracking_session_id"]
    assert json_data["status"] == "ACTIVE"

    # Start tracking session is idempotent
    response_retry = client.post(
        start_url,
        data={"source": "mobile-app", "device_metadata": {"os": "iOS"}},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_retry.status_code == 201
    assert response_retry.json()["tracking_session_id"] == session_id

    # 2. Record location point
    location_url = reverse("api_v1:record_location", args=[session_id])
    response = client.post(
        location_url,
        data={
            "latitude": -23.55052,
            "longitude": -46.633308,
            "accuracy_m": 5.0,
            "speed_kph": 50.0,
            "heading_deg": 180.0,
            "altitude_m": 750.0,
            "sequence": 1,
            "client_event_id": "evt-pt-1",
            "recorded_at": timezone.now().isoformat()
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 201
    json_data = response.json()
    assert json_data["sequence"] == 1

    # Record location point is idempotent by sequence & client_event_id
    response_dup = client.post(
        location_url,
        data={
            "latitude": -23.55052,
            "longitude": -46.633308,
            "accuracy_m": 5.0,
            "sequence": 1,
            "client_event_id": "evt-pt-1",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_dup.status_code == 201
    assert response_dup.json()["id"] == json_data["id"]

    # 3. Invalid location point parameters
    response_invalid = client.post(
        location_url,
        data={
            "latitude": -95.0,  # invalid latitude
            "longitude": -46.633308,
            "accuracy_m": 5.0,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_invalid.status_code == 409

    # 4. Batch telemetry sync
    batch_url = reverse("api_v1:record_location_batch", args=[session_id])
    response_batch = client.post(
        batch_url,
        data=[
            {
                "latitude": -23.551,
                "longitude": -46.634,
                "accuracy_m": 6.0,
                "sequence": 2,
                "client_event_id": "evt-pt-2"
            },
            {
                "latitude": -23.552,
                "longitude": -46.635,
                "accuracy_m": 4.5,
                "sequence": 3,
                "client_event_id": "evt-pt-3"
            }
        ],
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_batch.status_code == 201
    assert response_batch.json()["processed_count"] == 2

    # 5. End tracking session
    end_url = reverse("api_v1:end_tracking", args=[session_id])
    response_end = client.post(
        end_url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_end.status_code == 200
    assert response_end.json()["status"] == "ENDED"

    # End tracking session is idempotent
    response_end_dup = client.post(
        end_url,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_end_dup.status_code == 200
    assert response_end_dup.json()["session_id"] == session_id

    # 6. Ended tracking session rejects new points
    response_after_end = client.post(
        location_url,
        data={
            "latitude": -23.55052,
            "longitude": -46.633308,
            "accuracy_m": 5.0,
            "sequence": 4,
            "client_event_id": "evt-pt-4",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_after_end.status_code == 409
