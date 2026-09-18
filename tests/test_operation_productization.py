import pytest
from decimal import Decimal
from django.utils import timezone
from django.urls import reverse
from django.test import Client
from django.core.management import call_command
from io import StringIO
import uuid

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.freights.domain.enums import OperationStatus, FreightStopType
from src.freights.infrastructure.django.models import (
    FreightOperation,
    FreightOperationStop,
    ProofOfDelivery,
    FreightOperationCargoLot,
    TrackingSession
)
from src.freights.application.available_actions import CalculateDriverAvailableActionsService
from src.shared.interfaces.api.v1.auth import generate_access_token
from tests.test_api_v1_driver_operations import make_operation, grant


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
def user_a(db, django_user_model):
    return django_user_model.objects.create_user(username="usera", password="password")


@pytest.fixture
def driver_user(db, django_user_model):
    return django_user_model.objects.create_user(username="driveruser", password="password")


@pytest.fixture
def driver_a(db, org_a, driver_user):
    from src.drivers.infrastructure.django.models import Driver
    return Driver.objects.create(organization=org_a, user=driver_user, full_name="Driver A")


@pytest.mark.django_db
def test_available_actions_multi_stop(org_a, user_a, driver_a):
    """Test the complete multi-stop driver available actions sequence.

    Checks that available_actions matches validations, and next_stop progresses properly.
    """
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value)

    # Create baseline operation
    op = make_operation(org_a, user_a, driver_a, "MULT")

    # Set stops to:
    # 1. PICKUP
    # 2. PICKUP
    # 3. DELIVERY
    # 4. DELIVERY
    op.stops.all().delete()

    stop1 = FreightOperationStop.objects.create(
        operation=op, organization=org_a, sequence=1, stop_type="PICKUP", city="SP", state="SP", street="S1", number="1"
    )
    stop2 = FreightOperationStop.objects.create(
        operation=op, organization=org_a, sequence=2, stop_type="PICKUP", city="Campinas", state="SP", street="S2", number="2"
    )
    stop3 = FreightOperationStop.objects.create(
        operation=op, organization=org_a, sequence=3, stop_type="DELIVERY", city="Resende", state="RJ", street="S3", number="3"
    )
    stop4 = FreightOperationStop.objects.create(
        operation=op, organization=org_a, sequence=4, stop_type="DELIVERY", city="Rio", state="RJ", street="S4", number="4"
    )

    # Associate cargo lots to pickups and deliveries
    op.cargo_lots.all().delete()
    lot1 = FreightOperationCargoLot.objects.create(
        operation=op, description="Lot 1", weight_kg=100.0, pickup_stop=stop1, delivery_stop=stop3
    )
    lot2 = FreightOperationCargoLot.objects.create(
        operation=op, description="Lot 2", weight_kg=200.0, pickup_stop=stop2, delivery_stop=stop4
    )

    # -- Initial state (ASSIGNED) --
    assert op.status == "ASSIGNED"
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "START_OPERATION" in actions
    assert "ARRIVE_STOP" not in actions # cannot arrive yet
    assert CalculateDriverAvailableActionsService.get_next_stop(op) == stop1

    # -- Transition operation to DRIVER_EN_ROUTE_TO_PICKUP --
    op.status = "DRIVER_EN_ROUTE_TO_PICKUP"
    op.save()
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "ARRIVE_PICKUP" in actions
    assert "ARRIVE_STOP" in actions
    assert CalculateDriverAvailableActionsService.get_next_stop(op) == stop1

    # -- Arrive Stop 1 --
    stop1.status = "ARRIVED"
    stop1.save()
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "ARRIVE_PICKUP" in actions
    assert "COMPLETE_STOP" in actions

    # -- Transition operation to ARRIVED_AT_PICKUP --
    op.status = "ARRIVED_AT_PICKUP"
    op.save()
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "START_LOADING" in actions
    assert "COMPLETE_STOP" in actions

    # -- Start loading --
    op.status = "LOADING"
    op.save()
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "START_TRANSIT" in actions
    assert "COMPLETE_STOP" in actions

    # -- Complete Stop 1 and transition operation to IN_TRANSIT --
    stop1.status = "COMPLETED"
    stop1.save()
    op.status = "IN_TRANSIT"
    op.save()

    # Now next stop should be Stop 2
    assert CalculateDriverAvailableActionsService.get_next_stop(op) == stop2
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    # Can arrive stop 2 since stop 1 is completed
    assert "ARRIVE_STOP" in actions

    # -- Arrive and complete Stop 2 --
    stop2.status = "ARRIVED"
    stop2.save()
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "COMPLETE_STOP" in actions

    stop2.status = "COMPLETED"
    stop2.save()

    # Now next stop is Stop 3 (DELIVERY)
    assert CalculateDriverAvailableActionsService.get_next_stop(op) == stop3
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "ARRIVE_DELIVERY" in actions
    assert "ARRIVE_STOP" in actions # Stop 3 is next

    # -- Arrive Stop 3 --
    stop3.status = "ARRIVED"
    stop3.save()

    # Transition operation to ARRIVED_AT_DELIVERY
    op.status = "ARRIVED_AT_DELIVERY"
    op.save()

    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "START_UNLOADING" in actions
    # Stop 3 is delivery, no POD registered yet -> must SUBMIT_POD
    assert "SUBMIT_POD" in actions
    assert "COMPLETE_STOP" not in actions # cannot complete delivery without POD

    # -- Record POD for Stop 3 --
    pod3 = ProofOfDelivery.objects.create(
        operation=op,
        stop=stop3,
        receiver_name="Recebedor 3",
        delivered_at=timezone.now(),
    )

    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "START_UNLOADING" in actions
    assert "COMPLETE_STOP" in actions
    assert "SUBMIT_POD" not in actions

    # -- Transition operation to UNLOADING --
    op.status = "UNLOADING"
    op.save()

    # -- Complete Stop 3 --
    stop3.status = "COMPLETED"
    stop3.save()

    # Next stop is Stop 4 (DELIVERY)
    assert CalculateDriverAvailableActionsService.get_next_stop(op) == stop4
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "ARRIVE_STOP" in actions

    # -- Arrive Stop 4 --
    stop4.status = "ARRIVED"
    stop4.save()
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "SUBMIT_POD" in actions
    assert "COMPLETE_STOP" not in actions

    # -- Record POD for Stop 4 --
    pod4 = ProofOfDelivery.objects.create(
        operation=op,
        stop=stop4,
        receiver_name="Recebedor 4",
        delivered_at=timezone.now(),
    )

    # Now that POD is submitted, they can complete stop 4
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "COMPLETE_STOP" in actions

    # -- Complete Stop 4 --
    stop4.status = "COMPLETED"
    stop4.save()

    # All stops completed!
    assert CalculateDriverAvailableActionsService.get_next_stop(op) is None

    # Since all delivery stops are completed and have PODs, COMPLETE_OPERATION is available
    actions = CalculateDriverAvailableActionsService.get_available_actions(op)
    assert "COMPLETE_OPERATION" in actions


@pytest.mark.django_db
def test_driver_api_details_and_actions(org_a, user_a, driver_a):
    """Test mobile driver detail view endpoint returning actions and next stop correctly."""
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value)
    op = make_operation(org_a, user_a, driver_a, "APIT")

    # Generate mobile token
    token = generate_access_token(driver_a.user)

    client = Client()
    url = reverse("api_v1:driver_operation_detail", kwargs={"uuid": str(op.id)})

    response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200

    data = response.json()
    assert "available_actions" in data
    assert "next_stop" in data
    assert data["next_stop"]["sequence"] == 1
    assert "START_OPERATION" in action_codes(data)


@pytest.mark.django_db
def test_control_tower_filtering_searching_sorting(org_a, user_a, driver_a):
    """Test Nexa Control Tower list filtering, text search, and sorting options."""
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value)

    # Setup test operations
    op1 = make_operation(org_a, user_a, driver_a, "LIST1")
    op1.status = "IN_TRANSIT"
    op1.save()

    # Check that query prefetching and filtering works
    client = Client()
    client.force_login(user_a)

    url = reverse("backoffice:freight_operations")

    # Filter by Status
    response = client.get(url, {"status": "IN_TRANSIT"})
    assert response.status_code == 200
    assert len(response.context["freight_operations"]) == 1

    # Search by Driver name
    response = client.get(url, {"search": "Driver A"})
    assert response.status_code == 200
    assert len(response.context["freight_operations"]) == 1

    # Search by partial UUID cast check
    short_uuid = str(op1.id)[:8]
    response = client.get(url, {"search": short_uuid})
    assert response.status_code == 200
    assert len(response.context["freight_operations"]) == 1

    # Sort by SLA
    response = client.get(url, {"order_by": "SLA"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_detail_view_pods_and_thermal(org_a, user_a, driver_a):
    """Test Nexa operation detail page context and post-actions for POD and Incidents."""
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value)
    op = make_operation(org_a, user_a, driver_a, "DET1")

    # Setup stops statuses so delivery stop can receive a POD
    # Stop 1 (PICKUP) -> status COMPLETED
    # Stop 2 (DELIVERY) -> status ARRIVED
    stop_pickup = op.stops.filter(stop_type="PICKUP").first()
    stop_delivery = op.stops.filter(stop_type="DELIVERY").first()

    stop_pickup.status = "COMPLETED"
    stop_pickup.save()
    stop_delivery.status = "ARRIVED"
    stop_delivery.save()

    client = Client()
    client.force_login(user_a)

    url = reverse("backoffice:freight_operation_detail", kwargs={"pk": str(op.id)})
    response = client.get(url)
    assert response.status_code == 200
    assert "stops" in response.context
    assert "incidents" in response.context

    # Test recording a stop-level POD from the backoffice
    pod_url = reverse("backoffice:freight_operation_record_pod", kwargs={"pk": str(op.id)})

    delivered_at_str = timezone.now().isoformat()
    post_data = {
        "receiver_name": "Backoffice Receiver",
        "delivered_at": delivered_at_str,
        "notes": "Test POD notes from Nexa",
        "stop_id": str(stop_delivery.id)
    }

    response = client.post(pod_url, post_data)
    assert response.status_code == 302 # redirects to detail view

    # Verify POD is recorded at stop level
    assert ProofOfDelivery.objects.filter(operation=op, stop=stop_delivery).exists()
