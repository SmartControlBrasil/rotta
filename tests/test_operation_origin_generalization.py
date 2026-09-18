import pytest
from io import StringIO
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from django.test import RequestFactory
from django.contrib.auth import get_user_model

from src.organizations.infrastructure.django.models import Organization, Membership
from src.organizations.domain.enums import OrganizationType
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.freights.infrastructure.django.models import (
    FreightOperation,
    FreightOperationStop,
    ProofOfDelivery,
    FreightOfferSelection,
    FreightOfferInterest,
    FreightOffer,
    FreightRequest,
    FreightRequestStop,
)
from src.freights.domain.enums import (
    OperationSource,
    OperationStatus,
    TrackingSessionStatus,
)
from src.freights.application.operation_services import (
    create_operation_from_selection,
    change_stop_status,
    report_operation_incident,
    record_proof_of_delivery,
)
from src.freights.application.tracking_services import (
    start_tracking_session,
    record_location_point,
)
from src.freights.application.reporting.operations_report import get_operations_report
from src.freights.application.reporting.people_report import get_carriers_report, get_drivers_report
from src.shared.interfaces.api.v1.auth import generate_access_token
from django.urls import reverse
from src.identity.infrastructure.django.models import Role, MembershipRole

def grant_permission_to_user(user, org, role_code):
    role = Role.objects.get(code=role_code)
    membership, _ = Membership.objects.get_or_create(user=user, organization=org, defaults={"status": "ACTIVE"})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())

@pytest.fixture
def org_carrier(db):
    return Organization.objects.create(name="CarrierOrg", type=OrganizationType.TRANSPORT_COMPANY)

@pytest.fixture
def carrier_profile(db, org_carrier):
    return CarrierProfile.objects.create(
        organization=org_carrier,
        tenant=org_carrier,
        trade_name="Carrier Corp",
        email="carrier_corp@example.com",
        status="ACTIVE",
    )

@pytest.fixture
def driver_user(db, org_carrier):
    User = get_user_model()
    u = User.objects.create_user(username="driver_john", password="password")
    Membership.objects.create(user=u, organization=org_carrier, status="ACTIVE")
    return u

@pytest.fixture
def driver(db, org_carrier, driver_user):
    return Driver.objects.create(
        organization=org_carrier,
        user=driver_user,
        full_name="John Doe",
        status="ACTIVE",
    )

@pytest.fixture
def vehicle(db, org_carrier):
    return Vehicle.objects.create(
        organization=org_carrier,
        plate="ABC1234",
        model="Cargo Truck",
    )

@pytest.mark.django_db
def test_marketplace_operation_requires_selection(org_carrier, carrier_profile, driver, vehicle):
    # Attempting to save a MARKETPLACE operation without a selection must raise a ValidationError
    op = FreightOperation(
        organization=org_carrier,
        carrier=carrier_profile,
        driver=driver,
        vehicle=vehicle,
        source_type=OperationSource.MARKETPLACE,
        selection=None,
    )
    with pytest.raises(ValidationError) as excinfo:
        op.save()
    assert "selection" in excinfo.value.message_dict

@pytest.mark.django_db
def test_non_marketplace_operation_creation(org_carrier, carrier_profile, driver, vehicle):
    # Creating a MANUAL operation without a selection is allowed
    op = FreightOperation.objects.create(
        organization=org_carrier,
        carrier=carrier_profile,
        driver=driver,
        vehicle=vehicle,
        source_type=OperationSource.MANUAL,
        selection=None,
    )
    assert op.id is not None
    assert op.source_type == OperationSource.MANUAL
    assert op.selection is None

@pytest.mark.django_db
def test_execution_flows_without_selection(rbac_ready, org_carrier, carrier_profile, driver, vehicle, driver_user):
    grant_permission_to_user(driver_user, org_carrier, "DRIVER")
    op = FreightOperation.objects.create(
        organization=org_carrier,
        carrier=carrier_profile,
        driver=driver,
        vehicle=vehicle,
        source_type=OperationSource.MANUAL,
        selection=None,
    )

    # 1. Operational stops
    stop = FreightOperationStop.objects.create(
        organization=org_carrier,
        operation=op,
        sequence=1,
        stop_type="DELIVERY",
        status="PENDING",
        city="Sao Paulo",
        state="SP",
    )

    # Can advance stop status
    change_stop_status(
        operation_id=str(op.id),
        stop_id=str(stop.id),
        new_status="ARRIVED",
        actor=driver_user,
    )
    stop.refresh_from_db()
    assert stop.status == "ARRIVED"

    # 2. Tracking session
    session = start_tracking_session(
        actor=driver_user,
        operation_id=str(op.id),
    )
    assert session is not None

    point = record_location_point(
        actor=driver_user,
        tracking_session_id=str(session.id),
        latitude=-23.55,
        longitude=-46.63,
        accuracy_m=5.0,
    )
    assert point is not None

    # 3. Incidents
    incident = report_operation_incident(
        operation_id=str(op.id),
        actor=driver_user,
        description="Furo no pneu",
        driver_only=True,
    )
    assert incident is not None

    # 4. Proof of Delivery
    pod = record_proof_of_delivery(
        operation_id=str(op.id),
        actor=driver_user,
        receiver_name="Alice",
        delivered_at=timezone.now(),
        driver_only=True,
        stop_id=str(stop.id),
    )
    assert pod is not None

@pytest.mark.django_db
def test_detail_view_and_reports_tolerance(client, rbac_ready, org_carrier, carrier_profile, driver, vehicle, driver_user):
    grant_permission_to_user(driver_user, org_carrier, "DRIVER")
    op = FreightOperation.objects.create(
        organization=org_carrier,
        carrier=carrier_profile,
        driver=driver,
        vehicle=vehicle,
        source_type=OperationSource.MANUAL,
        selection=None,
    )

    # Detail view call via HTTP client
    token = generate_access_token(driver_user)
    detail_url = reverse("api_v1:driver_operation_detail", args=[op.id])
    response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200

    # Reporting logic runs without selection crashes
    filters = {}
    ops_report = get_operations_report(driver_user, filters)
    assert ops_report is not None

    carriers_rep = get_carriers_report(driver_user, filters)
    assert carriers_rep is not None

    drivers_rep = get_drivers_report(driver_user, filters)
    assert drivers_rep is not None
