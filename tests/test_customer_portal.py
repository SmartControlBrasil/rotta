import pytest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.domain.enums import FreightCargoProfile
from src.freights.infrastructure.django.models import FreightRequest, FreightRequestStop, FreightRequestCargo
from src.customers.infrastructure.django.models import Customer


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership, _ = Membership.objects.get_or_create(
        user=user,
        organization=organization,
        defaults={"status": "ACTIVE"}
    )
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.get_or_create(membership=membership, role=role, defaults={"scope": scope})
    return membership


@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def org_customer_a(db):
    return Organization.objects.create(
        name="Customer Org A",
        type=OrganizationType.CUSTOMER,
    )


@pytest.fixture
def org_customer_b(db):
    return Organization.objects.create(
        name="Customer Org B",
        type=OrganizationType.CUSTOMER,
    )


@pytest.fixture
def user_customer_a(db, django_user_model):
    return django_user_model.objects.create_user(username="cust_a_web", password="password")


@pytest.fixture
def user_customer_b(db, django_user_model):
    return django_user_model.objects.create_user(username="cust_b_web", password="password")


@pytest.fixture
def user_no_membership(db, django_user_model):
    return django_user_model.objects.create_user(username="no_membership_web", password="password")


@pytest.fixture
def customer_profile_a(db, org_customer_a, user_customer_a):
    return Customer.objects.create(
        organization=org_customer_a,
        legal_name="Empresa A LTDA",
        trade_name="Empresa A",
        document_number="11222333000181",
        email="empresa_a@example.com",
        owner=user_customer_a,
        status="ACTIVE"
    )


@pytest.fixture
def customer_profile_b(db, org_customer_b, user_customer_b):
    return Customer.objects.create(
        organization=org_customer_b,
        legal_name="Empresa B LTDA",
        trade_name="Empresa B",
        document_number="22333444000181",
        email="empresa_b@example.com",
        owner=user_customer_b,
        status="ACTIVE"
    )


@pytest.mark.django_db
def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("customer:dashboard"))
    assert response.status_code == 302
    assert "login" in response.url


@pytest.mark.django_db
def test_authenticated_customer_accesses_dashboard(client, org_customer_a, user_customer_a, customer_profile_a, rbac_ready):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    client.force_login(user_customer_a)
    response = client.get(reverse("customer:dashboard"), HTTP_HOST="localhost")
    assert response.status_code == 200
    assert "Empresa A" in response.content.decode()


@pytest.mark.django_db
def test_authenticated_user_without_customer_denied(client, user_no_membership, rbac_ready):
    client.force_login(user_no_membership)
    response = client.get(reverse("customer:dashboard"), HTTP_HOST="localhost")
    # Mixin will raise PermissionDenied which Django maps to 403
    assert response.status_code == 403


@pytest.mark.django_db
def test_customer_list_isolation(
    client,
    org_customer_a,
    org_customer_b,
    user_customer_a,
    user_customer_b,
    customer_profile_a,
    customer_profile_b,
    rbac_ready
):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    grant(user_customer_b, org_customer_b, RoleCode.CUSTOMER.value)

    # A's request
    client.force_login(user_customer_a)
    client.post(
        reverse("customer:freight_requests_new"),
        data={
            "origin": "Itapevi - SP",
            "destination": "Barueri - SP",
            "cargo_description": "Carga de A",
            "weight_kg": "1500",
            "service_type": "ON_DEMAND",
        },
        HTTP_HOST="localhost"
    )

    # B's request
    client.force_login(user_customer_b)
    client.post(
        reverse("customer:freight_requests_new"),
        data={
            "origin": "Joinville - SC",
            "destination": "Curitiba - PR",
            "cargo_description": "Carga de B",
            "weight_kg": "2500",
            "service_type": "ON_DEMAND",
        },
        HTTP_HOST="localhost"
    )

    # List as A
    client.force_login(user_customer_a)
    response = client.get(reverse("customer:freight_requests_list"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Carga de A" in content
    assert "Carga de B" not in content

    # List as B
    client.force_login(user_customer_b)
    response = client.get(reverse("customer:freight_requests_list"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Carga de B" in content
    assert "Carga de A" not in content


@pytest.mark.django_db
def test_detail_view_and_idor_prevention(
    client,
    org_customer_a,
    org_customer_b,
    user_customer_a,
    user_customer_b,
    customer_profile_a,
    customer_profile_b,
    rbac_ready
):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    grant(user_customer_b, org_customer_b, RoleCode.CUSTOMER.value)

    # A creates a request
    client.force_login(user_customer_a)
    client.post(
        reverse("customer:freight_requests_new"),
        data={
            "origin": "Itapevi - SP",
            "destination": "Barueri - SP",
            "cargo_description": "Carga de A",
            "weight_kg": "1500",
            "service_type": "ON_DEMAND",
        },
        HTTP_HOST="localhost"
    )
    req_a = FreightRequest.objects.filter(customer=customer_profile_a).first()

    # 1. A details own request - allowed (200)
    response = client.get(
        reverse("customer:freight_request_detail", kwargs={"uuid": req_a.id}),
        HTTP_HOST="localhost"
    )
    assert response.status_code == 200
    assert "Carga de A" in response.content.decode()

    # 2. B attempts to detail A's request - blocked with 404 (IDOR Prevention)
    client.force_login(user_customer_b)
    response = client.get(
        reverse("customer:freight_request_detail", kwargs={"uuid": req_a.id}),
        HTTP_HOST="localhost"
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_new_freight_request_creation_scenarios(client, org_customer_a, user_customer_a, customer_profile_a, rbac_ready):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    client.force_login(user_customer_a)

    # 1. GET new request form
    response = client.get(reverse("customer:freight_requests_new"), HTTP_HOST="localhost")
    assert response.status_code == 200

    # 2. POST Dry cargo + Scheduled future date
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    response = client.post(
        reverse("customer:freight_requests_new"),
        data={
            "origin": "Itapevi - SP",
            "destination": "Barueri - SP",
            "service_type": "SCHEDULED",
            "when": tomorrow,
            "cargo_description": "Carga seca agendada",
            "weight_kg": "2200",
        },
        HTTP_HOST="localhost"
    )
    # Redirects to detail view
    assert response.status_code == 302
    req = FreightRequest.objects.get(cargo__description="Carga seca agendada")
    assert req.cargo.cargo_profile == FreightCargoProfile.DRY_CARGO.value
    assert req.pickup_stop.scheduled_date.isoformat() == tomorrow

    # 3. POST Refrigerated cargo + On Demand
    response = client.post(
        reverse("customer:freight_requests_new"),
        data={
            "origin": "Joinville - SC",
            "destination": "Curitiba - PR",
            "service_type": "ON_DEMAND",
            "cargo_description": "Carga fria de queijo",
            "weight_kg": "1200.5",
            "refrigerated": "on",
        },
        HTTP_HOST="localhost"
    )
    assert response.status_code == 302
    req_ref = FreightRequest.objects.get(cargo__description="Carga fria de queijo")
    assert req_ref.cargo.cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value
    assert req_ref.pickup_stop.scheduled_date == timezone.localdate()


@pytest.mark.django_db
def test_form_validation_errors(client, org_customer_a, user_customer_a, customer_profile_a, rbac_ready):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    client.force_login(user_customer_a)

    # 1. Missing required field (origin)
    response = client.post(
        reverse("customer:freight_requests_new"),
        data={
            "destination": "Barueri - SP",
            "cargo_description": "Carga Teste",
            "weight_kg": "1500",
            "service_type": "ON_DEMAND",
        },
        HTTP_HOST="localhost"
    )
    assert response.status_code == 200
    assert "Origem é obrigatória" in response.content.decode()

    # 2. Scheduling in the past
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    response = client.post(
        reverse("customer:freight_requests_new"),
        data={
            "origin": "Itapevi - SP",
            "destination": "Barueri - SP",
            "service_type": "SCHEDULED",
            "when": yesterday,
            "cargo_description": "Carga no passado",
            "weight_kg": "1500",
        },
        HTTP_HOST="localhost"
    )
    assert response.status_code == 200
    assert "no passado" in response.content.decode()
