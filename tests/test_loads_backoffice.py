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
from src.freights.domain.enums import FreightCargoProfile, FreightCargoType, FreightRequestStatus
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


def make_cargo(organization, user, ref, is_refrigerated=False):
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
        status=FreightRequestStatus.SUBMITTED.value,
    )
    
    # Create stops
    FreightRequestStop.objects.create(
        freight_request=request,
        sequence=1,
        stop_type="PICKUP",
        city="São Paulo",
        state="SP",
    )
    FreightRequestStop.objects.create(
        freight_request=request,
        sequence=2,
        stop_type="DELIVERY",
        city="Rio de Janeiro",
        state="RJ",
    )

    cargo_profile = FreightCargoProfile.REFRIGERATED_CARGO.value if is_refrigerated else FreightCargoProfile.DRY_CARGO.value
    cargo = FreightRequestCargo.objects.create(
        freight_request=request,
        description=f"Cargo Description {ref}",
        cargo_type=FreightCargoType.GENERAL_CARGO.value,
        cargo_profile=cargo_profile,
        quantity=Decimal("100"),
        weight_kg=Decimal("1500"),
        volume_m3=Decimal("5.5"),
        package_count=10,
        package_type="Pallet",
        temperature_min_c=Decimal("-18.0") if is_refrigerated else None,
        temperature_max_c=Decimal("-10.0") if is_refrigerated else None,
        target_temperature_c=Decimal("-15.0") if is_refrigerated else None,
    )
    return cargo


def link_offer_and_operation(cargo, organization, user, ref):
    request = cargo.freight_request
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
        status="ASSIGNED",
        assigned_at=timezone.now(),
    )
    return offer, operation


@pytest.mark.django_db
def test_anonymous_redirects_to_login(client, org_a, user_a):
    cargo = make_cargo(org_a, user_a, "A")
    
    response = client.get(reverse("backoffice:cargas"))
    assert response.status_code == 302
    assert "login" in response.url

    response = client.get(reverse("backoffice:cargas_detail", args=[cargo.id]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_authorized_user_accesses_list(client, org_a, user_a, rbac_ready):
    make_cargo(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    client.force_login(user_a)
    response = client.get(reverse("backoffice:cargas"), HTTP_HOST="localhost")
    assert response.status_code == 200


@pytest.mark.django_db
def test_unauthorized_user_receives_403(client, org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.FINANCIAL_ANALYST.value, AccessScope.COMPANY.value)

    client.force_login(user_a)
    response = client.get(reverse("backoffice:cargas"), HTTP_HOST="localhost")
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_respects_scoping(client, org_a, org_b, user_a, user_b, rbac_ready):
    cargo_a = make_cargo(org_a, user_a, "A")
    cargo_b = make_cargo(org_b, user_b, "B")

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    response = client.get(reverse("backoffice:cargas"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert str(cargo_a.id)[:8] in content
    assert str(cargo_b.id)[:8] not in content


@pytest.mark.django_db
def test_list_presents_dry_and_refrigerated_cargo(client, org_a, user_a, rbac_ready):
    cargo_dry = make_cargo(org_a, user_a, "DRY", is_refrigerated=False)
    cargo_ref = make_cargo(org_a, user_a, "REF", is_refrigerated=True)

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    response = client.get(reverse("backoffice:cargas"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Seca" in content
    assert "Refrigerada" in content
    assert str(cargo_dry.id)[:8] in content
    assert str(cargo_ref.id)[:8] in content


@pytest.mark.django_db
def test_detail_view_presents_all_fields_and_relationships(client, org_a, user_a, rbac_ready):
    cargo = make_cargo(org_a, user_a, "A", is_refrigerated=True)
    offer, operation = link_offer_and_operation(cargo, org_a, user_a, "A")

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    response = client.get(reverse("backoffice:cargas_detail", args=[cargo.id]), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()

    # Features / Physical characteristics
    assert "Cargo Description A" in content
    assert "1500" in content  # Weight
    assert "5.5" in content   # Volume
    assert "10x Pallet" in content # Count/type
    
    # Temperature conditions
    assert "-18" in content
    assert "-10" in content
    assert "-15" in content

    # Navigation / links
    assert f"/app/freight-requests/{cargo.freight_request.id}" in content
    assert f"/app/freight-offers/{offer.id}" in content
    assert f"/app/freight-operations/{operation.id}" in content
    
    # Client & stops
    assert "Customer-A" in content
    assert "São Paulo/SP" in content
    assert "Rio de Janeiro/RJ" in content


@pytest.mark.django_db
def test_filters(client, org_a, user_a, rbac_ready):
    cargo_dry = make_cargo(org_a, user_a, "DRY", is_refrigerated=False)
    cargo_ref = make_cargo(org_a, user_a, "REF", is_refrigerated=True)

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    # 1. Filter by Refrigerated
    response = client.get(reverse("backoffice:cargas") + "?cargo_profile=REFRIGERATED_CARGO", HTTP_HOST="localhost")
    content = response.content.decode()
    assert str(cargo_ref.id)[:8] in content
    assert str(cargo_dry.id)[:8] not in content

    # 2. Filter by Dry
    response = client.get(reverse("backoffice:cargas") + "?cargo_profile=DRY_CARGO", HTTP_HOST="localhost")
    content = response.content.decode()
    assert str(cargo_dry.id)[:8] in content
    assert str(cargo_ref.id)[:8] not in content


@pytest.mark.django_db
def test_sidebar_contains_cargas_link_and_embarques_placeholder(client, org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    response = client.get(reverse("backoffice:dashboard"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    
    # Cargas is functional
    assert "/app/cargas/" in content
    
    # Embarques is placeholder and unclickable / show "Em breve"
    assert "Embarques" in content
    assert "Em breve" in content
