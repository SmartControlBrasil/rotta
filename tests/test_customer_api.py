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
from src.shared.interfaces.api.v1.auth import generate_access_token


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
    return django_user_model.objects.create_user(username="cust_a", password="password")


@pytest.fixture
def user_customer_b(db, django_user_model):
    return django_user_model.objects.create_user(username="cust_b", password="password")


@pytest.fixture
def user_no_membership(db, django_user_model):
    return django_user_model.objects.create_user(username="no_membership", password="password")


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
def test_create_simplified_freight_request_success(client, org_customer_a, user_customer_a, customer_profile_a, rbac_ready):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    token = generate_access_token(user_customer_a)

    payload = {
        "origin": "Itapevi - SP",
        "destination": "Barueri - SP",
        "service_type": "ON_DEMAND",
        "cargo": {
            "description": "3 pallets de autopeças",
            "approx_weight_kg": 1800,
            "refrigerated": False
        },
        "notes": "Coleta nas docas 2",
        "contact": "Falar com João"
    }

    response = client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["status"] == "DRAFT"
    assert data["origin"]["city"] == "Itapevi"
    assert data["origin"]["state"] == "SP"
    assert data["destination"]["city"] == "Barueri"
    assert data["destination"]["state"] == "SP"
    assert data["cargo"]["description"] == "3 pallets de autopeças"
    assert data["cargo"]["weight_kg"] == 1800.0
    assert data["cargo"]["refrigerated"] is False
    assert data["notes"] == "Coleta nas docas 2"
    assert data["contact"] == "Falar com João"


@pytest.mark.django_db
def test_create_freight_request_refrigerated_and_scheduled(client, org_customer_a, user_customer_a, customer_profile_a, rbac_ready):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    token = generate_access_token(user_customer_a)

    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    payload = {
        "origin": "Joinville - SC",
        "destination": "Curitiba - PR",
        "service_type": "SCHEDULED",
        "when": tomorrow,
        "cargo": {
            "description": "Carga fria de laticínios",
            "approx_weight_kg": 3500.5,
            "refrigerated": True
        }
    }

    response = client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )

    assert response.status_code == 201
    data = response.json()
    assert data["cargo"]["refrigerated"] is True
    assert data["scheduled_date"] == tomorrow

    # Verify database persistence
    fr = FreightRequest.objects.get(id=data["id"])
    assert fr.cargo.cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value
    assert fr.pickup_stop.scheduled_date.isoformat() == tomorrow


@pytest.mark.django_db
def test_create_freight_request_validation_errors(client, org_customer_a, user_customer_a, customer_profile_a, rbac_ready):
    grant(user_customer_a, org_customer_a, RoleCode.CUSTOMER.value)
    token = generate_access_token(user_customer_a)

    # Missing origin
    payload = {
        "destination": "Barueri - SP",
        "cargo": {"description": "Test Cargo"}
    }
    response = client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 400
    assert "Origem e destino" in response.json()["error"]["message"]

    # Past date
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    payload = {
        "origin": "Itapevi - SP",
        "destination": "Barueri - SP",
        "service_type": "SCHEDULED",
        "when": yesterday,
        "cargo": {"description": "Test Cargo"}
    }
    response = client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 400
    assert "no passado" in response.json()["error"]["message"]


@pytest.mark.django_db
def test_list_freight_requests_isolation(
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

    # Create one request for A, one for B
    token_a = generate_access_token(user_customer_a)
    token_b = generate_access_token(user_customer_b)

    payload = {
        "origin": "Itapevi - SP",
        "destination": "Barueri - SP",
        "cargo": {"description": "Cargo de A"}
    }
    client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )

    payload = {
        "origin": "Santos - SP",
        "destination": "Campinas - SP",
        "cargo": {"description": "Cargo de B"}
    }
    client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_b}"
    )

    # List as A
    response_a = client.get(
        reverse("api_v1:customer_freight_requests"),
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_a.status_code == 200
    assert response_a.json()["count"] == 1
    assert response_a.json()["results"][0]["cargo"]["description"] == "Cargo de A"

    # List as B
    response_b = client.get(
        reverse("api_v1:customer_freight_requests"),
        HTTP_AUTHORIZATION=f"Bearer {token_b}"
    )
    assert response_b.status_code == 200
    assert response_b.json()["count"] == 1
    assert response_b.json()["results"][0]["cargo"]["description"] == "Cargo de B"


@pytest.mark.django_db
def test_detail_freight_request_and_idor(
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

    token_a = generate_access_token(user_customer_a)
    token_b = generate_access_token(user_customer_b)

    # A creates request
    payload = {
        "origin": "Itapevi - SP",
        "destination": "Barueri - SP",
        "cargo": {"description": "Cargo de A"}
    }
    resp_create = client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    req_id_a = resp_create.json()["id"]

    # 1. A details own request - should be allowed (200)
    response_detail_a = client.get(
        reverse("api_v1:customer_freight_request_detail", kwargs={"uuid": req_id_a}),
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response_detail_a.status_code == 200
    assert response_detail_a.json()["cargo"]["description"] == "Cargo de A"

    # 2. B attempts to detail A's request with valid UUID - should return 404 (IDOR Prevention)
    response_detail_b = client.get(
        reverse("api_v1:customer_freight_request_detail", kwargs={"uuid": req_id_a}),
        HTTP_AUTHORIZATION=f"Bearer {token_b}"
    )
    assert response_detail_b.status_code == 404


@pytest.mark.django_db
def test_create_freight_request_membership_required(client, user_no_membership, rbac_ready):
    # Authenticated user without active membership to a customer organization
    token = generate_access_token(user_no_membership)

    payload = {
        "origin": "Itapevi - SP",
        "destination": "Barueri - SP",
        "cargo": {"description": "Cargo sem organizacao"}
    }
    response = client.post(
        reverse("api_v1:customer_freight_requests"),
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    # The decorator should return 403 Forbidden because no customer profile is linked
    assert response.status_code == 403
    assert "not linked to any Customer profile" in response.json()["error"]["message"]
