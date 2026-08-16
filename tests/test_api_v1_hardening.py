import pytest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
import time

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.domain.enums import TrackingSessionStatus, OperationStatus
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestCargo,
    FreightRequestStop,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
)
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer
from src.shared.interfaces.api.v1.auth import (
    generate_access_token,
    generate_refresh_token,
    validate_access_token,
    validate_refresh_token,
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


@pytest.fixture
def driver_a(db, org_a, user_a):
    return Driver.objects.create(organization=org_a, user=user_a, full_name="Driver A")


@pytest.fixture
def driver_b(db, org_b, user_b):
    return Driver.objects.create(organization=org_b, user=user_b, full_name="Driver B")


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
    # Stops
    FreightRequestStop.objects.create(
        freight_request=request,
        sequence=1,
        stop_type="PICKUP",
        city="Cidade Origem",
        state="SP",
        street="Rua O",
        number="10",
        scheduled_date=timezone.now().date(),
    )
    FreightRequestStop.objects.create(
        freight_request=request,
        sequence=2,
        stop_type="DELIVERY",
        city="Cidade Destino",
        state="RJ",
        street="Av D",
        number="20",
        scheduled_date=timezone.now().date(),
    )
    # Cargo
    FreightRequestCargo.objects.create(
        freight_request=request,
        description=f"Cargo-{ref}",
        cargo_type="GENERAL_CARGO",
        cargo_profile="DRY_CARGO",
        weight_kg=Decimal("1000.00"),
        volume_m3=Decimal("5.00"),
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


@pytest.mark.django_db
def test_access_refresh_token_generation_and_refresh(client, user_a, driver_a):
    response = client.post(
        reverse("api_v1:login"),
        data={"username": "usera", "password": "password"},
        content_type="application/json",
    )
    assert response.status_code == 200
    json_data = response.json()
    assert "access_token" in json_data
    assert "refresh_token" in json_data
    assert json_data["expires_in"] == 900

    # Validate that we can refresh the access token using the refresh token
    refresh_url = reverse("api_v1:token_refresh")
    response_refresh = client.post(
        refresh_url,
        data={"refresh_token": json_data["refresh_token"]},
        content_type="application/json",
    )
    assert response_refresh.status_code == 200
    assert "access_token" in response_refresh.json()


@pytest.mark.django_db
def test_token_revocation(client, user_a, driver_a):
    # Log in
    response = client.post(
        reverse("api_v1:login"),
        data={"username": "usera", "password": "password"},
        content_type="application/json",
    )
    assert response.status_code == 200
    tokens = response.json()

    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    # Revoke tokens
    revoke_url = reverse("api_v1:token_revoke")
    response_revoke = client.post(
        revoke_url,
        data={"refresh_token": refresh},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert response_revoke.status_code == 200
    assert response_revoke.json()["success"] is True

    # Attempt to access me endpoint with revoked access token - should return 401
    response_me = client.get(
        reverse("api_v1:me"),
        HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert response_me.status_code == 401

    # Attempt to refresh with revoked refresh token - should return 401
    response_refresh = client.post(
        reverse("api_v1:token_refresh"),
        data={"refresh_token": refresh},
        content_type="application/json",
    )
    assert response_refresh.status_code == 401


@pytest.mark.django_db
def test_strict_driver_scoping_adversarial(client, org_a, org_b, user_a, driver_a, driver_b, rbac_ready):
    # Grant permissions so that driver_a's User ALSO has backoffice scoped view on org_b
    grant(user_a, org_b, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    # Make operation in org_b for driver_b
    op_b = make_operation(org_b, user_a, driver_b, "B")

    token_a = generate_access_token(user_a)

    # 1. Driver A gets list of operations - should NOT see driver B's operation even if they have org memberships in B
    response = client.get(
        reverse("api_v1:driver_operations"),
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0

    # 2. Driver A tries to advance status of Driver B's operation - should return 404 (not visible/invisible)
    advance_url = reverse("api_v1:advance_operation_status", args=[op_b.id])
    response_advance = client.post(
        advance_url,
        data={"next_status": "DRIVER_EN_ROUTE_TO_PICKUP"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_advance.status_code == 404


@pytest.mark.django_db
def test_driver_operations_pagination(client, org_a, user_a, driver_a):
    # Create 3 operations for driver_a
    op1 = make_operation(org_a, user_a, driver_a, "1")
    op2 = make_operation(org_a, user_a, driver_a, "2")
    op3 = make_operation(org_a, user_a, driver_a, "3")

    token = generate_access_token(user_a)

    # Page 1, page_size 2
    response = client.get(
        reverse("api_v1:driver_operations") + "?page=1&page_size=2",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["count"] == 3
    assert len(json_data["results"]) == 2
    assert "next" in json_data
    assert "page=2" in json_data["next"]
    assert json_data["previous"] is None

    # Page 2, page_size 2
    response_p2 = client.get(
        reverse("api_v1:driver_operations") + "?page=2&page_size=2",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response_p2.status_code == 200
    json_data_p2 = response_p2.json()
    assert len(json_data_p2["results"]) == 1
    assert json_data_p2["next"] is None
    assert "page=1" in json_data_p2["previous"]
