import pytest
import json
from decimal import Decimal
from django.utils import timezone
from django.urls import reverse
from django.test import Client
from django.core.management import call_command
from io import StringIO
import uuid

from src.identity.domain.enums import RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.domain.enums import OperationStatus, FreightStopType
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestCargo,
    FreightRequestStop,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    FreightOperationStop,
    ProofOfDelivery,
    FreightOperationCargoLot,
    TrackingSession
)
from src.shared.interfaces.api.v1.auth import generate_access_token
from tests.test_api_v1_driver_operations import grant


def action_codes(payload):
    return {item["action"] for item in payload["available_actions"]}


@pytest.fixture(autouse=True)
def run_bootstrap(db):
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
    from src.drivers.infrastructure.django.models import Driver
    return Driver.objects.create(organization=org_a, user=user_a, full_name="Driver A")


@pytest.fixture
def driver_b(db, org_b, user_b):
    from src.drivers.infrastructure.django.models import Driver
    return Driver.objects.create(organization=org_b, user=user_b, full_name="Driver B")


def make_smoke_operation(organization, user, driver, ref):
    import hashlib
    ref_hash = str(int(hashlib.md5(ref.encode('utf-8')).hexdigest(), 16))[:10]
    customer = from_customer_creation(organization, ref, ref_hash)

    request = FreightRequest.objects.create(
        organization=organization,
        customer=customer,
        created_by=user,
        owner=user,
        reference_code=f"REQ-{ref}",
        status="SUBMITTED",
    )

    # Create 4 stops: 2 PICKUP, 2 DELIVERY
    s1 = FreightRequestStop.objects.create(
        freight_request=request, sequence=1, stop_type="PICKUP",
        city="Sao Paulo", state="SP", street="Rua A", number="10",
        scheduled_date=timezone.now().date(),
    )
    s2 = FreightRequestStop.objects.create(
        freight_request=request, sequence=2, stop_type="PICKUP",
        city="Campinas", state="SP", street="Rua B", number="20",
        scheduled_date=timezone.now().date(),
    )
    s3 = FreightRequestStop.objects.create(
        freight_request=request, sequence=3, stop_type="DELIVERY",
        city="Resende", state="RJ", street="Rua C", number="30",
        scheduled_date=timezone.now().date(),
    )
    s4 = FreightRequestStop.objects.create(
        freight_request=request, sequence=4, stop_type="DELIVERY",
        city="Rio", state="RJ", street="Rua D", number="40",
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

    from src.carriers.infrastructure.django.models import CarrierProfile
    carrier, _ = CarrierProfile.objects.get_or_create(
        organization=organization,
        tenant=organization,
        defaults={
            "trade_name": f"Carrier-{ref}",
            "status": "ACTIVE",
            "email": f"carrier-{ref}@example.com",
        }
    )

    from src.vehicles.infrastructure.django.models import Vehicle
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

    # Relink/create stops at operation level and link to cargo lots
    operation.stops.all().delete()
    op_stop1 = FreightOperationStop.objects.create(
        operation=operation, organization=organization, sequence=1, stop_type="PICKUP", city="Sao Paulo", state="SP", street="Rua A", number="10"
    )
    op_stop2 = FreightOperationStop.objects.create(
        operation=operation, organization=organization, sequence=2, stop_type="PICKUP", city="Campinas", state="SP", street="Rua B", number="20"
    )
    op_stop3 = FreightOperationStop.objects.create(
        operation=operation, organization=organization, sequence=3, stop_type="DELIVERY", city="Resende", state="RJ", street="Rua C", number="30"
    )
    op_stop4 = FreightOperationStop.objects.create(
        operation=operation, organization=organization, sequence=4, stop_type="DELIVERY", city="Rio", state="RJ", street="Rua D", number="40"
    )

    FreightOperationCargoLot.objects.create(
        operation=operation, description="Lot 1", weight_kg=500.00, pickup_stop=op_stop1, delivery_stop=op_stop3
    )
    FreightOperationCargoLot.objects.create(
        operation=operation, description="Lot 2", weight_kg=500.00, pickup_stop=op_stop2, delivery_stop=op_stop4
    )

    return operation


def from_customer_creation(organization, ref, ref_hash):
    from src.customers.infrastructure.django.models import Customer
    return Customer.objects.create(
        organization=organization,
        legal_name=f"Customer-{ref}",
        document_number=f"12{ref_hash}",
        email=f"customer-{ref}@example.com",
    )


@pytest.mark.django_db
def test_pilot_smoke_flow_complete(org_a, org_b, user_a, user_b, driver_a, driver_b, django_capture_on_commit_callbacks):
    """E2E smoke test representing the complete logistical driver pilot scenario."""
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value)

    # 1. Create operation
    op = make_smoke_operation(org_a, user_a, driver_a, "SMK1")

    client = Client()

    # Login via REST API
    login_url = reverse("api_v1:login")
    login_res = client.post(
        login_url,
        data=json.dumps({"username": "usera", "password": "password"}),
        content_type="application/json"
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # 2. Fetch details and verify START_OPERATION is available
    detail_url = reverse("api_v1:driver_operation_detail", kwargs={"uuid": str(op.id)})
    res = client.get(detail_url, **auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "available_actions" in data
    assert "START_OPERATION" in action_codes(data)
    assert data["next_stop"]["sequence"] == 1
    stop1_id = data["next_stop"]["id"]

    # 3. START_OPERATION (macro transition -> DRIVER_EN_ROUTE_TO_PICKUP)
    # Confirm it's available first
    assert "START_OPERATION" in action_codes(data)
    advance_macro_url = reverse("api_v1:advance_operation_status", kwargs={"uuid": str(op.id)})

    with django_capture_on_commit_callbacks(execute=True):
        res = client.post(
            advance_macro_url,
            data=json.dumps({"next_status": "DRIVER_EN_ROUTE_TO_PICKUP"}),
            content_type="application/json",
            **auth_headers
        )
    assert res.status_code == 200

    # 4. Start tracking session
    start_tracking_url = reverse("api_v1:start_tracking", kwargs={"uuid": str(op.id)})
    res = client.post(
        start_tracking_url,
        data=json.dumps({"source": "mobile"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 201
    session_uuid = res.json()["tracking_session_id"]

    # 5. Send GPS point
    loc_url = reverse("api_v1:record_location", kwargs={"session_uuid": session_uuid})
    res = client.post(
        loc_url,
        data=json.dumps({
            "latitude": -23.5505,
            "longitude": -46.6333,
            "accuracy_m": 5.0,
            "recorded_at": timezone.now().isoformat()
        }),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 201

    # Refetch details
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert "ARRIVE_STOP" in action_codes(data)

    # 6. Stop 1 (PICKUP): Arrive
    advance_stop1_url = reverse(
        "api_v1:advance_stop_status",
        kwargs={"uuid": str(op.id), "stop_uuid": stop1_id}
    )
    res = client.post(
        advance_stop1_url,
        data=json.dumps({"next_status": "ARRIVED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Transition macro to ARRIVED_AT_PICKUP then LOADING
    res = client.post(
        advance_macro_url,
        data=json.dumps({"next_status": "ARRIVED_AT_PICKUP"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200
    res = client.post(
        advance_macro_url,
        data=json.dumps({"next_status": "LOADING"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Refetch details -> COMPLETE_STOP must be available
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert "COMPLETE_STOP" in action_codes(data)

    # Stop 1: Complete
    res = client.post(
        advance_stop1_url,
        data=json.dumps({"next_status": "COMPLETED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Transition macro to IN_TRANSIT
    res = client.post(
        advance_macro_url,
        data=json.dumps({"next_status": "IN_TRANSIT"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Refetch details -> next stop should be Stop 2
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert data["next_stop"]["sequence"] == 2
    stop2_id = data["next_stop"]["id"]
    assert "ARRIVE_STOP" in action_codes(data)

    # 7. Stop 2 (PICKUP): Arrive and Complete
    advance_stop2_url = reverse(
        "api_v1:advance_stop_status",
        kwargs={"uuid": str(op.id), "stop_uuid": stop2_id}
    )
    res = client.post(
        advance_stop2_url,
        data=json.dumps({"next_status": "ARRIVED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200
    res = client.post(
        advance_stop2_url,
        data=json.dumps({"next_status": "COMPLETED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Refetch details -> next stop should be Stop 3 (DELIVERY)
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert data["next_stop"]["sequence"] == 3
    stop3_id = data["next_stop"]["id"]

    # 8. Stop 3 (DELIVERY): Arrive
    advance_stop3_url = reverse(
        "api_v1:advance_stop_status",
        kwargs={"uuid": str(op.id), "stop_uuid": stop3_id}
    )
    res = client.post(
        advance_stop3_url,
        data=json.dumps({"next_status": "ARRIVED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Transition macro to ARRIVED_AT_DELIVERY
    res = client.post(
        advance_macro_url,
        data=json.dumps({"next_status": "ARRIVED_AT_DELIVERY"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Report incident
    incident_url = reverse("api_v1:report_incident", kwargs={"uuid": str(op.id)})
    with django_capture_on_commit_callbacks(execute=True):
        res = client.post(
            incident_url,
            data=json.dumps({"description": "Atraso no descarregamento"}),
            content_type="application/json",
            **auth_headers
        )
    assert res.status_code == 201

    # Attempt to Complete Stop 3 without POD -> must fail with HTTP 400
    res = client.post(
        advance_stop3_url,
        data=json.dumps({"next_status": "COMPLETED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 409

    # Submit POD for Stop 3
    pod_url = reverse("api_v1:record_pod", kwargs={"uuid": str(op.id)})
    res = client.post(
        pod_url,
        data=json.dumps({
            "receiver_name": "Carlos Recebedor",
            "delivered_at": timezone.now().isoformat(),
            "stop_id": stop3_id
        }),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 201

    # Refetch details -> now COMPLETE_STOP is available
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert "COMPLETE_STOP" in action_codes(data)

    # Complete Stop 3
    res = client.post(
        advance_stop3_url,
        data=json.dumps({"next_status": "COMPLETED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Transition macro to UNLOADING
    res = client.post(
        advance_macro_url,
        data=json.dumps({"next_status": "UNLOADING"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Refetch details -> next stop should be Stop 4 (DELIVERY)
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert data["next_stop"]["sequence"] == 4
    stop4_id = data["next_stop"]["id"]

    # 9. Stop 4 (DELIVERY): Arrive, POD, and Complete
    advance_stop4_url = reverse(
        "api_v1:advance_stop_status",
        kwargs={"uuid": str(op.id), "stop_uuid": stop4_id}
    )
    res = client.post(
        advance_stop4_url,
        data=json.dumps({"next_status": "ARRIVED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Submit POD for Stop 4
    res = client.post(
        pod_url,
        data=json.dumps({
            "receiver_name": "Aline Recebedora",
            "delivered_at": timezone.now().isoformat(),
            "stop_id": stop4_id
        }),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 201

    res = client.post(
        advance_stop4_url,
        data=json.dumps({"next_status": "COMPLETED"}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # Refetch details -> next stop is None, COMPLETE_OPERATION is available
    res = client.get(detail_url, **auth_headers)
    data = res.json()
    assert data["next_stop"] is None
    assert "COMPLETE_OPERATION" in action_codes(data)

    # 10. Finalize operation (transition macro to DELIVERED)
    with django_capture_on_commit_callbacks(execute=True):
        res = client.post(
            advance_macro_url,
            data=json.dumps({"next_status": "DELIVERED"}),
            content_type="application/json",
            **auth_headers
        )
    assert res.status_code == 200

    # End tracking session
    end_tracking_url = reverse("api_v1:end_tracking", kwargs={"session_uuid": session_uuid})
    res = client.post(
        end_tracking_url,
        data=json.dumps({}),
        content_type="application/json",
        **auth_headers
    )
    assert res.status_code == 200

    # 11. Validate backend outcomes & intelligence persistency
    from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
    repo = DjangoIntelligenceSnapshotRepository()

    # Verify snapshot history exists
    history = repo.history_for_operation(str(op.id), str(org_a.id))
    assert len(history) > 0

    # Test dataset record construction
    from src.intelligence.infrastructure.django.query_services import DjangoOperationResultContextQueryService
    from src.intelligence.application.dataset_services import BuildOperationalRiskDatasetService

    query_service = DjangoOperationResultContextQueryService()
    builder = BuildOperationalRiskDatasetService(repo, query_service)

    records = builder.build_dataset(
        organization_id=str(org_a.id),
        actor=user_a,
        start_date=timezone.now() - timezone.timedelta(days=1),
        end_date=timezone.now() + timezone.timedelta(days=1)
    )
    assert len(records) > 0
    assert records[-1].eligibility == "COMPLETE"
    assert records[-1].labels["delivered_on_time"] is None
    assert records[-1].labels["critical_incident_occurred"] is False

    # 12. Test driver ownership (motorista B tenta acessar)
    login_res_b = client.post(
        login_url,
        data=json.dumps({"username": "userb", "password": "password"}),
        content_type="application/json"
    )
    assert login_res_b.status_code == 200
    token_b = login_res_b.json()["access_token"]
    auth_headers_b = {"HTTP_AUTHORIZATION": f"Bearer {token_b}"}

    # Fetch details as driver B -> 404
    res_b = client.get(detail_url, **auth_headers_b)
    assert res_b.status_code == 404

    # Post advance status as driver B -> 404
    res_b = client.post(
        advance_macro_url,
        data=json.dumps({"next_status": "IN_TRANSIT"}),
        content_type="application/json",
        **auth_headers_b
    )
    assert res_b.status_code == 404

    # 13. Test cross-tenant (user_b tenta acessar como operador)
    from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset
    from src.identity.domain.enums import PermissionCode

    qs = scoped_freight_operations_queryset(user_b, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    assert not qs.filter(id=op.id).exists()
