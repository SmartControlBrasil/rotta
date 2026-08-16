import pytest
from io import StringIO
from django.core.management import call_command
from django.urls import reverse
from src.identity.infrastructure.django.models import User
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.identity.domain.enums import RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.drivers.infrastructure.django.models import Driver
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
def user_a(db, django_user_model):
    return django_user_model.objects.create_user(username="usera", password="password", email="usera@example.com")


@pytest.fixture
def driver_a(db, org_a, user_a):
    return Driver.objects.create(organization=org_a, user=user_a, full_name="Driver A")


@pytest.mark.django_db
def test_login_successful_with_username(client, user_a, driver_a):
    response = client.post(
        reverse("api_v1:login"),
        data={"username": "usera", "password": "password"},
        content_type="application/json",
    )
    assert response.status_code == 200
    json_data = response.json()
    assert "access_token" in json_data
    assert "refresh_token" in json_data


@pytest.mark.django_db
def test_login_successful_with_email(client, user_a, driver_a):
    response = client.post(
        reverse("api_v1:login"),
        data={"username": "usera@example.com", "password": "password"},
        content_type="application/json",
    )
    json_data = response.json()
    assert "access_token" in json_data
    assert "refresh_token" in json_data


@pytest.mark.django_db
def test_login_invalid_credentials(client, user_a):
    response = client.post(
        reverse("api_v1:login"),
        data={"username": "usera", "password": "wrong_password"},
        content_type="application/json",
    )
    assert response.status_code == 401
    assert "error" in response.json()


@pytest.mark.django_db
def test_login_missing_parameters(client):
    response = client.post(
        reverse("api_v1:login"),
        data={"username": "usera"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.django_db
def test_me_unauthorized(client):
    response = client.get(reverse("api_v1:me"))
    assert response.status_code == 401
    assert "error" in response.json()


@pytest.mark.django_db
def test_me_authorized(client, user_a, driver_a, rbac_ready):
    # Grant viewer role to user_a just so they have some permissions
    grant(user_a, driver_a.organization, RoleCode.VIEWER.value, AccessScope.COMPANY.value)
    
    token = generate_access_token(user_a)
    response = client.get(
        reverse("api_v1:me"),
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["username"] == "usera"
    assert json_data["email"] == "usera@example.com"
    assert json_data["driver"]["full_name"] == "Driver A"
    assert json_data["organization"]["name"] == "Org A"
    assert "capabilities" in json_data


@pytest.mark.django_db
def test_me_authorized_no_driver_profile(client, user_a):
    token = generate_access_token(user_a)
    response = client.get(
        reverse("api_v1:me"),
        HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert response.status_code == 403
    assert "error" in response.json()
    assert "not linked to any Driver profile" in response.json()["error"]["message"]
