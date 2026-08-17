import pytest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import PermissionDenied

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
from src.shared.interfaces.api.v1.auth import generate_access_token
from src.shared.interfaces.backoffice.authorization import (
    scoped_driver_queryset,
    scoped_vehicle_queryset,
    scoped_freight_operations_queryset,
    scoped_freight_request_queryset,
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
        status="PUBLISHED",
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
        status="ACTIVE",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest,
        organization=organization,
        offer=offer,
        status="PENDING_CONFIRMATION",
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
def test_driver_endpoints_strict_isolation(client, org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Setup operation for Driver B (belonging to Org B)
    op_b = make_operation(org_b, user_b, driver_b, "B")

    # Generate token for Driver A
    token_a = generate_access_token(user_a)

    # 1. Driver A lists operations - should only see their own (0 operations since Driver A has none)
    response = client.get(
        reverse("api_v1:driver_operations"),
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0

    # 2. Driver A tries to access detail of Driver B's operation - should return 404
    detail_url = reverse("api_v1:driver_operation_detail", args=[op_b.id])
    response_detail = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_detail.status_code == 404

    # 3. Driver A tries to advance status of Driver B's operation - should return 404
    advance_url = reverse("api_v1:advance_operation_status", args=[op_b.id])
    response_advance = client.post(
        advance_url,
        data={"next_status": "DRIVER_EN_ROUTE_TO_PICKUP"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_advance.status_code == 404

    # 4. Driver A tries to create incident on Driver B's operation - should return 404
    incident_url = reverse("api_v1:report_incident", args=[op_b.id])
    response_incident = client.post(
        incident_url,
        data={"description": "Incident report description"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_incident.status_code == 404

    # 5. Driver A tries to record POD on Driver B's operation - should return 404
    pod_url = reverse("api_v1:record_pod", args=[op_b.id])
    response_pod = client.post(
        pod_url,
        data={
            "receiver_name": "Test Receiver",
            "delivered_at": timezone.now().isoformat(),
            "latitude": -23.55052,
            "longitude": -46.633308,
            "notes": "Test POD notes",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_pod.status_code == 404


@pytest.mark.django_db
def test_carrier_cross_tenant_access_control(org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Setup data
    op_b = make_operation(org_b, user_b, driver_b, "B")
    veh_b = op_b.vehicle

    # Grant Operations Manager to user_a inside org_a
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    # Carrier A (Org A, User A) should not be able to fetch Carrier B's vehicle
    vehicles_qs = scoped_vehicle_queryset(user_a, PermissionCode.VEHICLES_VIEW.value)
    assert veh_b not in vehicles_qs

    # Carrier A should not be able to fetch Carrier B's driver
    drivers_qs = scoped_driver_queryset(user_a, PermissionCode.DRIVERS_VIEW.value)
    assert driver_b not in drivers_qs

    # Carrier A should not be able to fetch Carrier B's operation
    operations_qs = scoped_freight_operations_queryset(user_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_b not in operations_qs


@pytest.mark.django_db
def test_customer_cross_tenant_access_control(org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Make customer and request for Org B
    op_b = make_operation(org_b, user_b, driver_b, "B")
    req_b = op_b.selection.offer.freight_request

    # Grant Company Admin permission to user_a inside org_a
    grant(user_a, org_a, RoleCode.COMPANY_ADMIN.value, AccessScope.COMPANY.value)

    # User A (Org A) should not see Org B's freight request
    req_qs = scoped_freight_request_queryset(user_a, PermissionCode.FREIGHT_REQUESTS_VIEW.value)
    assert req_b not in req_qs


@pytest.mark.django_db
def test_organizational_scope_isolation(org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Same permission (FREIGHT_OPERATIONS_VIEW) granted to User A in Org A and User B in Org B
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    grant(user_b, org_b, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    op_b = make_operation(org_b, user_b, driver_b, "B")

    # User A should NOT see Org B's operations, even though they have the exact same role in Org A
    qs_a = scoped_freight_operations_queryset(user_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_b not in qs_a

    # User B should see Org B's operations
    qs_b = scoped_freight_operations_queryset(user_b, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_b in qs_b


@pytest.mark.django_db
def test_uuid_prediction_adversarial(client, org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Attacker (User A) knows the exact UUID of Org B's operation
    op_b = make_operation(org_b, user_b, driver_b, "B")
    known_uuid = op_b.id

    token_a = generate_access_token(user_a)

    # 1. Driver A gets detail view with valid predicted UUID - should return 404
    detail_url = reverse("api_v1:driver_operation_detail", args=[known_uuid])
    response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 404

    # 2. Driver A posts status change with predicted UUID - should return 404
    advance_url = reverse("api_v1:advance_operation_status", args=[known_uuid])
    response_advance = client.post(
        advance_url,
        data={"next_status": "DRIVER_EN_ROUTE_TO_PICKUP"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_advance.status_code == 404


@pytest.mark.django_db
def test_backoffice_offer_actions_idor(client, org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Setup data for Org B
    op_b = make_operation(org_b, user_b, driver_b, "B")
    offer_b = op_b.selection.offer
    interest_b = op_b.selection.interest
    selection_b = op_b.selection

    # Grant marketplace select to User A inside Org A
    grant(user_a, org_a, RoleCode.COMPANY_ADMIN.value, AccessScope.COMPANY.value)

    client.force_login(user_a)

    # 1. User A tries to select candidate from Org B's interest - should return 404
    select_url = reverse("backoffice:freight_offer_interest_select", kwargs={"interest_pk": interest_b.pk})
    response = client.post(select_url, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 2. User A tries to withdraw interest from Org B - should return 404
    withdraw_url = reverse("backoffice:freight_offer_interest_withdraw", kwargs={"interest_pk": interest_b.pk})
    response = client.post(withdraw_url, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 3. User A tries to cancel selection from Org B - should return 404
    cancel_url = reverse("backoffice:freight_offer_selection_cancel", kwargs={"selection_pk": selection_b.pk})
    response = client.post(cancel_url, data={"reason": "Test cancel IDOR"}, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 4. User A tries to confirm selection from Org B - should return 404
    confirm_url = reverse("backoffice:freight_offer_selection_confirm", kwargs={"selection_pk": selection_b.pk})
    response = client.post(confirm_url, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 5. User A tries to decline selection from Org B - should return 404
    decline_url = reverse("backoffice:freight_offer_selection_decline", kwargs={"selection_pk": selection_b.pk})
    response = client.post(decline_url, data={"reason": "OTHER"}, HTTP_HOST="localhost")
    assert response.status_code == 404


@pytest.mark.django_db
def test_backoffice_operation_actions_idor(client, org_a, org_b, user_a, user_b, driver_a, driver_b, rbac_ready):
    # Setup data for Org B
    op_b = make_operation(org_b, user_b, driver_b, "B")

    # Grant Operations Manager to User A inside Org A (which has all operations action permissions)
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    client.force_login(user_a)

    # 1. User A tries to advance status of Org B's operation - should return 404
    url = reverse("backoffice:freight_operation_advance_status", kwargs={"pk": op_b.pk})
    response = client.post(url, data={"next_status": "LOADING"}, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 2. User A tries to report incident on Org B's operation - should return 404
    url = reverse("backoffice:freight_operation_report_incident", kwargs={"pk": op_b.pk})
    response = client.post(url, data={"description": "Test incident"}, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 3. User A tries to cancel Org B's operation - should return 404
    url = reverse("backoffice:freight_operation_cancel", kwargs={"pk": op_b.pk})
    response = client.post(url, data={"reason": "Test cancel operation"}, HTTP_HOST="localhost")
    assert response.status_code == 404

    # 4. User A tries to record POD on Org B's operation - should return 404
    url = reverse("backoffice:freight_operation_record_pod", kwargs={"pk": op_b.pk})
    response = client.post(url, data={"receiver_name": "Test receiver", "delivered_at": timezone.now().isoformat()}, HTTP_HOST="localhost")
    assert response.status_code == 404
