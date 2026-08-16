import pytest
from datetime import date, timedelta
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.utils import timezone

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.infrastructure.django.models import (
    FreightRequest,
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
from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset


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
def admin_user(db, django_user_model):
    return django_user_model.objects.create_user(username="adminuser", password="password", is_superuser=True)


@pytest.fixture
def no_perm_user(db, django_user_model):
    return django_user_model.objects.create_user(username="noperm", password="password")


def make_operation(organization, user, ref):
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
    customer = Customer.objects.create(
        organization=organization,
        legal_name=f"Customer-{ref}",
        document_number=f"1234567890{ref}",
        email=f"customer-{ref}@example.com",
    )
    request = FreightRequest.objects.create(
        organization=organization,
        customer=customer,
        created_by=user,
        owner=user,
        reference_code=f"REQ-{ref}",
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
    return operation


@pytest.mark.django_db
def test_system_admin_sees_all(org_a, org_b, user_a, admin_user, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_a, "B")

    qs = scoped_freight_operations_queryset(admin_user, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_a in qs
    assert op_b in qs


@pytest.mark.django_db
def test_company_scope_limits_to_organization(org_a, org_b, user_a, user_b, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_b, "B")

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    qs = scoped_freight_operations_queryset(user_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_a in qs
    assert op_b not in qs


@pytest.mark.django_db
def test_own_scope_limits_to_owned_offers(org_a, user_a, user_b, rbac_ready):
    # op_a is created/owned by user_a
    op_a = make_operation(org_a, user_a, "A")
    # op_a2 is created by user_b inside org_a
    op_a2 = make_operation(org_a, user_b, "A2")

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.OWN.value)

    qs = scoped_freight_operations_queryset(user_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_a in qs
    assert op_a2 not in qs


@pytest.mark.django_db
def test_none_scope_returns_empty(org_a, user_a, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.NONE.value)

    qs = scoped_freight_operations_queryset(user_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_a not in qs
    assert qs.count() == 0


@pytest.mark.django_db
def test_no_permission_returns_empty(org_a, user_a, no_perm_user, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    # no_perm_user has no permissions/roles
    qs = scoped_freight_operations_queryset(no_perm_user, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert op_a not in qs
    assert qs.count() == 0
