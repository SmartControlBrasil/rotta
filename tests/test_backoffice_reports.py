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
from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightCargoType,
    FreightRequestStatus,
    OperationStatus,
    LoadType,
)
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestCargo,
    FreightRequestStop,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    ThermalReading,
    ThermalExcursion,
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
        name="Transportadora A",
        type=OrganizationType.TRANSPORT_COMPANY,
    )

@pytest.fixture
def org_b(db):
    return Organization.objects.create(
        name="Transportadora B",
        type=OrganizationType.TRANSPORT_COMPANY,
    )

@pytest.fixture
def user_admin(db, django_user_model):
    return django_user_model.objects.create_user(username="adminuser", password="password")

@pytest.fixture
def user_viewer(db, django_user_model):
    return django_user_model.objects.create_user(username="vieweruser", password="password")

@pytest.fixture
def user_unauthorized(db, django_user_model):
    return django_user_model.objects.create_user(username="unauthuser", password="password")

@pytest.fixture
def sample_data(org_a, org_b, user_admin):
    # Setup carrier, driver, vehicle
    carrier_a = CarrierProfile.objects.create(
        organization=org_a,
        tenant=org_a,
        trade_name="Carrier A",
        status="ACTIVE",
    )
    driver_a = Driver.objects.create(
        organization=org_a,
        full_name="Motorista A",
        document="11122233344",
        status="ACTIVE",
    )
    vehicle_a = Vehicle.objects.create(
        organization=org_a,
        plate="ABC1234",
        vehicle_type="TRUCK",
        status="ACTIVE",
        capacity_weight_kg=10000,
    )

    # Setup customer
    customer_a = Customer.objects.create(
        organization=org_a,
        legal_name="Customer A",
        trade_name="Customer A",
        document_number="12345678900",
        status="ACTIVE",
    )

    # Setup freight operation
    req = FreightRequest.objects.create(
        organization=org_a,
        customer=customer_a,
        created_by=user_admin,
        status=FreightRequestStatus.CLOSED.value,
    )
    cargo = FreightRequestCargo.objects.create(
        freight_request=req,
        cargo_type=FreightCargoType.GENERAL_CARGO.value,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value,
        weight_kg=5000,
        volume_m3=20,
        temperature_min_c=Decimal("2.00"),
        temperature_max_c=Decimal("8.00"),
    )
    # Stop for SLA verification
    stop1 = FreightRequestStop.objects.create(
        freight_request=req,
        stop_type="PICKUP",
        sequence=1,
        scheduled_date=(timezone.now() - timezone.timedelta(hours=2)).date(),
        window_start=(timezone.now() - timezone.timedelta(hours=2)).time(),
        window_end=(timezone.now() - timezone.timedelta(hours=1)).time(),
    )
    stop2 = FreightRequestStop.objects.create(
        freight_request=req,
        stop_type="DELIVERY",
        sequence=2,
        scheduled_date=(timezone.now() + timezone.timedelta(hours=1)).date(),
        window_start=(timezone.now() - timezone.timedelta(hours=1)).time(),
        window_end=(timezone.now() + timezone.timedelta(hours=1)).time(),
    )
    quote = FreightQuote.objects.create(
        organization=org_a,
        freight_request=req,
        status="APPROVED",
        created_by=user_admin,
    )
    offer = FreightOffer.objects.create(
        organization=org_a,
        freight_request=req,
        freight_quote=quote,
        created_by=user_admin,
        status="PUBLISHED",
        offer_amount=1500,
    )
    interest = FreightOfferInterest.objects.create(
        organization=org_a,
        offer=offer,
        carrier=carrier_a,
        driver=driver_a,
        vehicle=vehicle_a,
        status="CONFIRMED",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        organization=org_a,
        offer=offer,
        interest=interest,
        selected_by=user_admin,
        selected_at=timezone.now(),
        status="CONFIRMED",
    )
    op = FreightOperation.objects.create(
        organization=org_a,
        selection=selection,
        carrier=carrier_a,
        driver=driver_a,
        vehicle=vehicle_a,
        status=OperationStatus.DELIVERED.value,
        load_type=LoadType.FTL.value,
        created_at=timezone.now() - timezone.timedelta(days=1),
    )

    # Excursion setup
    ex = ThermalExcursion.objects.create(
        operation=op,
        sensor_id="SN-123",
        started_at=timezone.now() - timezone.timedelta(minutes=30),
        status="ACTIVE",
        direction="ABOVE_MAX",
        min_observed=Decimal("9.00"),
        max_observed=Decimal("9.50"),
    )
    return op


def test_reports_views_require_authentication(client):
    urls = [
        "backoffice:report_overview",
        "backoffice:report_operations",
        "backoffice:report_marketplace",
        "backoffice:report_carriers",
        "backoffice:report_drivers",
        "backoffice:report_fleet",
        "backoffice:report_sla",
        "backoffice:report_incidents",
        "backoffice:report_thermal",
        "backoffice:report_load_types",
    ]
    for url_name in urls:
        response = client.get(reverse(url_name))
        assert response.status_code == 302


def test_reports_views_access_denied_without_permission(rbac_ready, client, user_unauthorized, org_a):
    grant(user_unauthorized, org_a, "DRIVER")  # Driver doesn't have reports.view
    client.force_login(user_unauthorized)

    urls = [
        "backoffice:report_overview",
        "backoffice:report_operations",
    ]
    for url_name in urls:
        response = client.get(reverse(url_name))
        assert response.status_code == 403


def test_reports_views_allowed_with_permission(rbac_ready, client, user_viewer, org_a):
    grant(user_viewer, org_a, "VIEWER")  # Viewer has reports.view
    client.force_login(user_viewer)

    urls = [
        "backoffice:report_overview",
        "backoffice:report_operations",
        "backoffice:report_marketplace",
        "backoffice:report_carriers",
        "backoffice:report_drivers",
        "backoffice:report_fleet",
        "backoffice:report_sla",
        "backoffice:report_incidents",
        "backoffice:report_thermal",
        "backoffice:report_load_types",
    ]
    for url_name in urls:
        response = client.get(reverse(url_name))
        assert response.status_code == 200


def test_reports_scoping_and_metrics(rbac_ready, client, org_a, org_b, user_admin, sample_data):
    # user_admin belongs to org_a
    grant(user_admin, org_a, "SYSTEM_ADMIN", scope=AccessScope.COMPANY)
    client.force_login(user_admin)

    # Overview
    response = client.get(reverse("backoffice:report_overview"))
    assert response.status_code == 200
    assert response.context["kpis"]["operations_total"] == 1
    assert response.context["kpis"]["ftl_total"] == 1
    assert response.context["kpis"]["excursions_total"] == 1

    # Operations & Fretes
    response = client.get(reverse("backoffice:report_operations"))
    assert response.status_code == 200
    assert response.context["kpis"]["total_ops"] == 1
    assert response.context["kpis"]["total_value"] == 1500.0

    # Marketplace
    response = client.get(reverse("backoffice:report_marketplace"))
    assert response.status_code == 200
    assert response.context["kpis"]["requests_created"] == 1

    # Carriers
    response = client.get(reverse("backoffice:report_carriers"))
    assert response.status_code == 200
    assert len(response.context["table_data"]) == 1
    assert response.context["table_data"][0]["trade_name"] == "Carrier A"

    # Thermal
    response = client.get(reverse("backoffice:report_thermal"))
    assert response.status_code == 200
    assert response.context["kpis"]["refrigerated_operations"] == 1
    assert response.context["kpis"]["open_excursions"] == 1


def test_reports_csv_export(rbac_ready, client, org_a, user_admin, sample_data):
    grant(user_admin, org_a, "SYSTEM_ADMIN", scope=AccessScope.COMPANY)
    client.force_login(user_admin)

    # Export operations CSV
    response = client.get(reverse("backoffice:report_operations") + "?export=csv")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "operacoes_fretes.csv" in response["Content-Disposition"]

    content = b"".join(response.streaming_content).decode("utf-8")
    assert "Referência" in content
    assert "ABC1234" in content
    assert "Carrier A" in content
