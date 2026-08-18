import pytest
from io import StringIO
from decimal import Decimal
from datetime import timedelta
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.drivers.infrastructure.django.models import Driver, DriverRouteIntent
from src.vehicles.infrastructure.django.models import Vehicle, DriverVehicleAssignment
from src.audit.infrastructure.django.models import AuditLog
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
def org_a(db):
    return Organization.objects.create(name="Driver Org A", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Driver Org B", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def user_driver_a(db, django_user_model):
    return django_user_model.objects.create_user(username="driver_a_user", password="password")


@pytest.fixture
def user_driver_b(db, django_user_model):
    return django_user_model.objects.create_user(username="driver_b_user", password="password")


@pytest.fixture
def driver_profile_a(db, org_a, user_driver_a):
    return Driver.objects.create(
        organization=org_a,
        user=user_driver_a,
        full_name="Driver A",
        status="ACTIVE",
    )


@pytest.fixture
def driver_profile_b(db, org_b, user_driver_b):
    return Driver.objects.create(
        organization=org_b,
        user=user_driver_b,
        full_name="Driver B",
        status="ACTIVE",
    )


@pytest.fixture
def token_a(driver_profile_a):
    return generate_access_token(driver_profile_a.user)


@pytest.fixture
def token_b(driver_profile_b):
    return generate_access_token(driver_profile_b.user)


@pytest.mark.django_db(transaction=True)
def test_driver_preferences_get_and_put_ownership(client, token_a, token_b):
    # 1. GET initial empty preferences for Driver A
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}
    response = client.get(reverse("api_v1:driver_preferences"), **headers)
    assert response.status_code == 200
    data = response.json()
    assert data["base_city"] == ""
    assert data["preferred_radius_km"] is None

    # 2. PUT valid preferences for Driver A
    payload = {
        "base_city": "Itapevi",
        "base_state": "SP",
        "base_postal_code": "06696-000",
        "base_latitude": -23.5489,
        "base_longitude": -46.9314,
        "preferred_radius_km": 50,
        "preferred_regions": [{"city": "Barueri", "state": "SP"}, {"city": "Cotia", "state": "SP"}],
        "avoided_regions": [{"city": "Guarulhos", "state": "SP"}]
    }
    response = client.put(
        reverse("api_v1:driver_preferences"),
        data=payload,
        content_type="application/json",
        **headers
    )
    assert response.status_code == 200, f"Error details: {response.content}"
    data = response.json()
    assert data["base_city"] == "Itapevi"
    assert data["preferred_radius_km"] == 50
    assert len(data["preferred_regions"]) == 2
    assert len(data["avoided_regions"]) == 1

    # Check AuditLog
    assert AuditLog.objects.filter(action="driver_preferences_updated").exists()

    # 3. GET preferences as Driver B - must be empty/different (Tenant/Driver Isolation)
    headers_b = {"HTTP_AUTHORIZATION": f"Bearer {token_b}"}
    response_b = client.get(reverse("api_v1:driver_preferences"), **headers_b)
    assert response_b.status_code == 200
    data_b = response_b.json()
    assert data_b["base_city"] == ""


@pytest.mark.django_db(transaction=True)
def test_driver_preferences_validation(client, token_a):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}

    # 1. Invalid Latitude
    payload = {"base_latitude": 95.0}
    response = client.put(reverse("api_v1:driver_preferences"), data=payload, content_type="application/json", **headers)
    assert response.status_code == 400
    assert "Latitude" in response.json()["error"]["message"]

    # 2. Invalid Longitude
    payload = {"base_longitude": -185.0}
    response = client.put(reverse("api_v1:driver_preferences"), data=payload, content_type="application/json", **headers)
    assert response.status_code == 400
    assert "Longitude" in response.json()["error"]["message"]

    # 3. Invalid Radius (negative or zero)
    payload = {"preferred_radius_km": 0}
    response = client.put(reverse("api_v1:driver_preferences"), data=payload, content_type="application/json", **headers)
    assert response.status_code == 400
    assert "Raio preferencial" in response.json()["error"]["message"]


@pytest.mark.django_db(transaction=True)
def test_driver_route_intent_crud_and_validation(client, org_a, driver_profile_a, token_a, token_b):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}

    # 1. Create valid DESTINATION_PREFERENCE Route Intent
    tomorrow = timezone.now() + timedelta(days=1)
    day_after = tomorrow + timedelta(days=1)
    
    payload = {
        "intent_type": "DESTINATION_PREFERENCE",
        "origin_city": "Itapevi",
        "origin_state": "SP",
        "destination_city": "Sorocaba",
        "destination_state": "SP",
        "available_from": tomorrow.isoformat(),
        "available_until": day_after.isoformat(),
        "cargo_preference": "DRY_CARGO",
        "notes": "Voltando pra casa"
    }
    
    response = client.post(
        reverse("api_v1:driver_route_intents"),
        data=payload,
        content_type="application/json",
        **headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["intent_type"] == "DESTINATION_PREFERENCE"
    assert data["status"] == "ACTIVE"
    
    intent_id = data["id"]

    # Check AuditLog
    assert AuditLog.objects.filter(action="driver_route_intent_created", target_id=intent_id).exists()
    assert AuditLog.objects.filter(action="driver_route_intent_activated", target_id=intent_id).exists()

    # 2. GET driver A's intents
    response = client.get(reverse("api_v1:driver_route_intents"), **headers)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1

    # 3. Driver B cannot list/see Driver A's intents (Ownership check)
    headers_b = {"HTTP_AUTHORIZATION": f"Bearer {token_b}"}
    response = client.get(reverse("api_v1:driver_route_intents"), **headers_b)
    assert response.status_code == 200
    assert len(response.json()["results"]) == 0

    # 4. Driver B cannot cancel Driver A's intent (Security check / IDOR)
    response = client.post(
        reverse("api_v1:cancel_driver_route_intent", kwargs={"uuid": intent_id}),
        **headers_b
    )
    assert response.status_code == 404

    # 5. Driver A cancels own intent (Success)
    response = client.post(
        reverse("api_v1:cancel_driver_route_intent", kwargs={"uuid": intent_id}),
        **headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert AuditLog.objects.filter(action="driver_route_intent_cancelled", target_id=intent_id).exists()


@pytest.mark.django_db(transaction=True)
def test_driver_route_intent_time_validation(client, token_a):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}

    # available_until <= available_from
    tomorrow = timezone.now() + timedelta(days=1)
    payload = {
        "intent_type": "DESTINATION_PREFERENCE",
        "origin_city": "Itapevi",
        "origin_state": "SP",
        "destination_city": "Sorocaba",
        "destination_state": "SP",
        "available_from": tomorrow.isoformat(),
        "available_until": tomorrow.isoformat(),
    }
    
    response = client.post(reverse("api_v1:driver_route_intents"), data=payload, content_type="application/json", **headers)
    assert response.status_code == 400
    assert "Disponível até deve ser posterior" in response.json()["error"]["message"]


@pytest.mark.django_db(transaction=True)
def test_driver_route_intent_vehicle_validation(client, org_a, driver_profile_a, token_a):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}

    # 1. Create a Vehicle associated with org_a
    vehicle_ok = Vehicle.objects.create(
        organization=org_a,
        plate="OKK1A11",
        vehicle_type="CAR",
        status="ACTIVE",
    )
    
    # 2. Create another Vehicle associated with org_a but not assigned to the driver
    vehicle_unassigned = Vehicle.objects.create(
        organization=org_a,
        plate="BAD1A11",
        vehicle_type="CAR",
        status="ACTIVE",
    )

    # Establish assignment for vehicle_ok
    DriverVehicleAssignment.objects.create(
        driver=driver_profile_a,
        vehicle=vehicle_ok,
        active=True,
        valid_from=timezone.now().date(),
    )

    tomorrow = timezone.now() + timedelta(days=1)
    day_after = tomorrow + timedelta(days=1)

    # 3. Post with vehicle_unassigned (incompatible)
    payload = {
        "intent_type": "RETURN_LOAD",
        "origin_city": "Itapevi",
        "origin_state": "SP",
        "destination_city": "Sorocaba",
        "destination_state": "SP",
        "available_from": tomorrow.isoformat(),
        "available_until": day_after.isoformat(),
        "vehicle_id": str(vehicle_unassigned.id),
    }
    response = client.post(reverse("api_v1:driver_route_intents"), data=payload, content_type="application/json", **headers)
    assert response.status_code == 400
    assert "operacional ativo" in response.json()["error"]["message"]

    # 4. Post with vehicle_ok (compatible)
    payload["vehicle_id"] = str(vehicle_ok.id)
    response = client.post(reverse("api_v1:driver_route_intents"), data=payload, content_type="application/json", **headers)
    assert response.status_code == 201
