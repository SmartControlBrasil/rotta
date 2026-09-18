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
    FreightRequestStop,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    ProofOfDelivery,
)
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer
from src.shared.interfaces.api.v1.auth import generate_access_token


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
    from src.organizations.infrastructure.django.models import Membership
    membership_existed = Membership.objects.filter(user=user, organization=organization).exists()
    temp_membership = None
    if not membership_existed:
        temp_membership = Membership.objects.create(user=user, organization=organization, status="ACTIVE")
    try:
        from src.freights.application.operation_services import create_operation_from_selection
        operation = create_operation_from_selection(selection_id=str(selection.id), actor=user)
    finally:
        if temp_membership:
            temp_membership.delete()
    return operation


@pytest.mark.django_db
def test_driver_sees_own_operations(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    token = generate_access_token(user_a)

    response = client.get(
        reverse("api_v1:driver_operations"),
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["count"] == 1
    assert json_data["results"][0]["id"] == str(op.id)
    assert json_data["results"][0]["status"] == "ASSIGNED"


@pytest.mark.django_db
def test_driver_does_not_see_another_drivers_operation(client, org_a, org_b, user_a, user_b, driver_a, driver_b):
    # Make operation for driver_b (user_b)
    op_b = make_operation(org_b, user_b, driver_b, "B")

    # Authenticate as user_a (driver_a)
    token_a = generate_access_token(user_a)

    # User A gets operations list - should be empty because driver_a has no operations
    response = client.get(
        reverse("api_v1:driver_operations"),
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0

    # User A tries to get User B's operation detail directly - should return 404
    detail_url = reverse("api_v1:driver_operation_detail", args=[op_b.id])
    response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_driver_operation_detail_payload(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    token = generate_access_token(user_a)
    detail_url = reverse("api_v1:driver_operation_detail", args=[op.id])

    response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == str(op.id)
    assert json_data["status"] == "ASSIGNED"
    assert json_data["origin"]["city"] == "Cidade Origem"
    assert json_data["destination"]["city"] == "Cidade Destino"
    assert len(json_data["stops"]) == 2
    assert json_data["cargo"]["description"] == "Cargo-A"
    assert json_data["cargo"]["weight_kg"] == 1000.0


@pytest.mark.django_db
def test_driver_operation_advance_status(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    token = generate_access_token(user_a)
    advance_url = reverse("api_v1:advance_operation_status", args=[op.id])

    # 1. Valid Transition: ASSIGNED -> DRIVER_EN_ROUTE_TO_PICKUP
    response = client.post(
        advance_url,
        data={"next_status": "DRIVER_EN_ROUTE_TO_PICKUP"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DRIVER_EN_ROUTE_TO_PICKUP"

    # 2. Invalid Transition: DRIVER_EN_ROUTE_TO_PICKUP -> DELIVERED (fails because must go to PICKUP/LOADING etc and needs POD)
    response = client.post(
        advance_url,
        data={"next_status": "DELIVERED"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.django_db
def test_driver_operation_incidents(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    token = generate_access_token(user_a)
    incidents_url = reverse("api_v1:report_incident", args=[op.id])

    response = client.post(
        incidents_url,
        data={"description": "Pneu furado na BR-116", "client_event_id": "evt-inc-1"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 201
    json_data = response.json()
    assert json_data["event_type"] == "INCIDENT_REPORTED"
    assert "occurred_at" in json_data


@pytest.mark.django_db
def test_driver_operation_proof_of_delivery(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    token = generate_access_token(user_a)
    pod_url = reverse("api_v1:record_pod", args=[op.id])

    # First, must transition operation to UNLOADING before POD can be registered
    op.status = OperationStatus.UNLOADING.value
    op.save()

    response = client.post(
        pod_url,
        data={
            "receiver_name": "João Recebedor",
            "delivered_at": timezone.now().isoformat(),
            "latitude": -23.55,
            "longitude": -46.63,
            "notes": "Entregue com sucesso."
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 201
    json_data = response.json()
    assert json_data["status"] == "SUBMITTED"
    assert json_data["receiver_name"] == "João Recebedor"
    assert ProofOfDelivery.objects.filter(operation=op).exists()


@pytest.mark.django_db
def test_driver_operations_list_enrichment(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    op.load_type = "FTL"
    op.save()

    token = generate_access_token(user_a)
    response = client.get(
        reverse("api_v1:driver_operations"),
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    res = response.json()["results"][0]
    assert res["load_type"] == "FTL"
    # No planned deadline or timestamps -> service_level_state is None
    assert res["service_level_state"] is None


@pytest.mark.django_db
def test_driver_operation_detail_enrichment(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    op.load_type = "LTL"
    op.eta = timezone.now() + timezone.timedelta(hours=2)
    op.delay_minutes = 15
    op.save()

    # Create a thermal reading
    from src.freights.infrastructure.django.models import ThermalReading, FreightOperationEvent
    thermal = ThermalReading.objects.create(
        operation=op,
        device_id="sensor-123",
        sensor_timestamp=timezone.now() - timezone.timedelta(minutes=5),
        temperature_c=Decimal("4.50"),
        is_valid=True,
        metadata={"quality": "HIGH"}
    )

    # Let's set temperature control on cargo to test within_range
    cargo = op.selection.offer.freight_request.cargo
    cargo.temperature_min_c = Decimal("2.00")
    cargo.temperature_max_c = Decimal("8.00")
    cargo.save()
    op.temperature_min_c = Decimal("2.00")
    op.temperature_max_c = Decimal("8.00")
    op.save()

    # Let's set window_end on delivery stop to make sure a real deadline exists
    import datetime
    delivery_stop = op.selection.offer.freight_request.stops.filter(stop_type="DELIVERY").first()
    delivery_stop.window_end = datetime.time(18, 0)
    delivery_stop.save()
    op_d_stop = op.stops.filter(stop_type="DELIVERY").first()
    if op_d_stop:
        op_d_stop.window_end = datetime.time(18, 0)
        op_d_stop.save()

    # Add a custom event to the timeline
    event = FreightOperationEvent.objects.create(
        operation=op,
        event_type="INCIDENT_REPORTED",
        actor=user_a,
        origin="MOBILE_APP",
        occurred_at=timezone.now() - timezone.timedelta(minutes=10),
        notes="Custom incident"
    )

    token = generate_access_token(user_a)
    detail_url = reverse("api_v1:driver_operation_detail", args=[op.id])
    response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["load_type"] == "LTL"
    assert data["eta"] is not None
    assert data["delay_minutes"] == 15

    # Since delivery stop planned window exists, service_level should be present
    assert data["service_level"] is not None
    # op.delay_minutes is 15 (> 0), so state must be DELAYED
    assert data["service_level"]["state"] == "DELAYED"
    assert data["service_level"]["computed_delay_minutes"] == 15

    # Thermal summary verification
    assert data["thermal_summary"] is not None
    assert data["thermal_summary"]["latest_temperature_c"] == 4.5
    assert data["thermal_summary"]["validity"] is True
    assert data["thermal_summary"]["quality"] == "HIGH"
    assert data["thermal_summary"]["within_range"] is True

    # Timeline verification
    assert len(data["timeline"]) >= 1
    assert data["timeline"][0]["id"] == str(event.id)
    assert data["timeline"][0]["event_type"] == "INCIDENT_REPORTED"
    assert data["timeline"][0]["recorded_at"] is not None
    assert data["timeline"][0]["actor"]["username"] == "usera"
    assert data["timeline"][0]["source"] == "MOBILE_APP"


@pytest.mark.django_db
def test_driver_operation_enrichment_absence_of_data(client, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "A")
    op.events.all().delete()
    # Empty thermal readings, empty events, no load_type
    token = generate_access_token(user_a)
    detail_url = reverse("api_v1:driver_operation_detail", args=[op.id])
    response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["load_type"] is None
    assert data["eta"] is None
    assert data["delay_minutes"] is None
    assert data["thermal_summary"] is None
    assert data["timeline"] == []


@pytest.mark.django_db
def test_operation_timeline_sorting(db, org_a, user_a, driver_a):
    from src.freights.infrastructure.django.models import FreightOperationEvent
    op = make_operation(org_a, user_a, driver_a, "A")
    op.events.all().delete()

    # Create 3 events with different occurred_at / received_at
    now = timezone.now()
    e3 = FreightOperationEvent.objects.create(
        operation=op,
        event_type="INCIDENT_REPORTED",
        occurred_at=now + timezone.timedelta(minutes=10),
        origin="SYSTEM"
    )
    e1 = FreightOperationEvent.objects.create(
        operation=op,
        event_type="STATUS_CHANGED",
        occurred_at=now - timezone.timedelta(minutes=10),
        origin="SYSTEM"
    )
    e2 = FreightOperationEvent.objects.create(
        operation=op,
        event_type="OPERATION_CREATED",
        occurred_at=now,
        origin="SYSTEM"
    )

    # Sort deterministicamente
    events = list(op.events.order_by("occurred_at", "received_at", "id"))
    assert events[0].id == e1.id
    assert events[1].id == e2.id
    assert events[2].id == e3.id
