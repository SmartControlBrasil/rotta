from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.application.services import CarrierData, create_carrier
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.vehicles.application.services import (
    RefrigerationProfileData,
    VehicleData,
    change_vehicle_operational_status,
    change_vehicle_status,
    link_vehicle_to_carrier,
    register_vehicle,
    unlink_vehicle_from_carrier,
    update_vehicle,
    upsert_refrigeration_profile,
)
from src.vehicles.domain.enums import (
    RefrigerationControlType,
    VehicleBodyType,
    VehicleCargoProfile,
    VehicleOperationalStatus,
    VehicleOwnershipType,
    VehicleStatus,
    VehicleType,
)
from src.vehicles.infrastructure.django.models import RefrigerationProfile, Vehicle


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def tenant():
    return Organization.objects.create(
        name="Tenant Veiculos",
        legal_name="Tenant Veiculos LTDA",
        document="11222333000181",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_tenant():
    return Organization.objects.create(
        name="Outro Tenant Veiculos",
        legal_name="Outro Tenant Veiculos LTDA",
        document="22333444000181",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.mark.django_db(transaction=True)
def test_vehicle_identification_normalizes_plate_and_renavam(tenant):
    vehicle = register_vehicle(
        data=VehicleData(
            organization=tenant,
            plate="abc-1d23",
            renavam="6398.8444-200",
            vehicle_type=VehicleType.VUC,
            body_type=VehicleBodyType.BAU,
            ownership_type=VehicleOwnershipType.OWNED,
        )
    )
    assert vehicle.plate == "ABC1D23"
    assert vehicle.renavam == "63988444200"
    assert vehicle.masked_renavam == "639***00"

    invalid = Vehicle(
        organization=tenant,
        plate="BAD",
        vehicle_type=VehicleType.VUC,
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()


@pytest.mark.django_db(transaction=True)
def test_refrigeration_profile_requires_valid_temperature_range(tenant):
    dry = register_vehicle(
        data=VehicleData(
            organization=tenant,
            plate="AAA1B11",
            vehicle_type=VehicleType.TOCO,
            cargo_profile=VehicleCargoProfile.DRY_CARGO,
        )
    )
    with pytest.raises(ValidationError):
        upsert_refrigeration_profile(
            vehicle=dry,
            data=RefrigerationProfileData(
                temperature_min_c=Decimal("-10"),
                temperature_max_c=Decimal("0"),
            ),
        )

    refrigerated = register_vehicle(
        data=VehicleData(
            organization=tenant,
            plate="BBB1C22",
            vehicle_type=VehicleType.TRUCK,
            cargo_profile=VehicleCargoProfile.REFRIGERATED_CARGO,
        )
    )
    with pytest.raises(ValidationError):
        upsert_refrigeration_profile(
            vehicle=refrigerated,
            data=RefrigerationProfileData(
                temperature_min_c=Decimal("3"),
                temperature_max_c=Decimal("2"),
                control_type=RefrigerationControlType.DIGITAL,
            ),
        )

    profile = upsert_refrigeration_profile(
        vehicle=refrigerated,
        data=RefrigerationProfileData(
            temperature_min_c=Decimal("-18"),
            temperature_max_c=Decimal("4"),
            default_setpoint_c=Decimal("-10"),
            control_type=RefrigerationControlType.DIGITAL,
        ),
    )
    assert isinstance(profile, RefrigerationProfile)
    assert profile.temperature_min_c == Decimal("-18")


@pytest.mark.django_db(transaction=True)
def test_vehicle_status_operational_and_refrigeration_are_audited(tenant, django_user_model):
    actor = django_user_model.objects.create_user(username="vehicle-ops", password="safe-pass-123")
    vehicle = register_vehicle(
        data=VehicleData(
            organization=tenant,
            plate="CCC1D33",
            vehicle_type=VehicleType.VAN,
            cargo_profile=VehicleCargoProfile.BOTH,
            ownership_type=VehicleOwnershipType.AGGREGATED,
        ),
        actor=actor,
    )
    update_vehicle(
        vehicle,
        actor=actor,
        brand="Marca",
        model="Modelo",
        operational_status=VehicleOperationalStatus.AVAILABLE,
    )
    change_vehicle_status(vehicle, status=VehicleStatus.ACTIVE, actor=actor)
    change_vehicle_operational_status(
        vehicle,
        operational_status=VehicleOperationalStatus.MAINTENANCE,
        actor=actor,
    )
    upsert_refrigeration_profile(
        vehicle=vehicle,
        actor=actor,
        data=RefrigerationProfileData(
            temperature_min_c=Decimal("-12"),
            temperature_max_c=Decimal("3"),
            default_setpoint_c=Decimal("-8"),
        ),
    )
    assert AuditLog.objects.filter(action="vehicle_updated", target_id=str(vehicle.id)).exists()
    assert AuditLog.objects.filter(
        action="vehicle_status_changed", target_id=str(vehicle.id)
    ).exists()
    assert AuditLog.objects.filter(
        action="vehicle_operational_status_changed",
        target_id=str(vehicle.id),
    ).exists()
    refrigeration_log = AuditLog.objects.filter(
        action="vehicle_refrigeration_updated", target_id=str(vehicle.id)
    ).latest("created_at")
    assert refrigeration_log.after["temperature_min_c"] == "-12"
    assert refrigeration_log.after["temperature_max_c"] == "3"


@pytest.mark.django_db(transaction=True)
def test_vehicle_carrier_link_has_audit(tenant, django_user_model):
    actor = django_user_model.objects.create_user(
        username="vehicle-carrier", password="safe-pass-123"
    )
    carrier = create_carrier(
        data=CarrierData(tenant=tenant, organization=tenant, email="carrier@rotta.com"),
        actor=actor,
    )
    vehicle = register_vehicle(
        data=VehicleData(
            organization=tenant,
            plate="DDD1E44",
            vehicle_type=VehicleType.CARRETA,
            cargo_profile=VehicleCargoProfile.DRY_CARGO,
        ),
        actor=actor,
    )
    link = link_vehicle_to_carrier(vehicle=vehicle, carrier=carrier, actor=actor)
    unlink_vehicle_from_carrier(link, actor=actor)
    assert AuditLog.objects.filter(action="vehicle_carrier_linked", target_id=str(link.id)).exists()
    assert AuditLog.objects.filter(
        action="vehicle_carrier_unlinked", target_id=str(link.id)
    ).exists()


@pytest.mark.django_db
def test_backoffice_vehicle_routes_rbac_multitenancy_and_idor(
    client, django_user_model, rbac_ready, tenant, other_tenant
):
    manager = django_user_model.objects.create_user(
        username="vehicle-manager", password="safe-pass-123"
    )
    outsider = django_user_model.objects.create_user(
        username="vehicle-outsider", password="safe-pass-123"
    )
    grant(manager, tenant, RoleCode.OPERATIONS_MANAGER, AccessScope.COMPANY)
    grant(outsider, tenant, RoleCode.VIEWER, AccessScope.COMPANY)

    visible = Vehicle.objects.create(
        organization=tenant,
        plate="EEE1F55",
        vehicle_type=VehicleType.VUC,
    )
    hidden = Vehicle.objects.create(
        organization=other_tenant,
        plate="FFF1G66",
        vehicle_type=VehicleType.VUC,
    )

    assert client.get(reverse("backoffice:vehicles")).status_code == 302
    client.force_login(outsider)
    assert client.get(reverse("backoffice:vehicle_create")).status_code == 403

    client.force_login(manager)
    assert client.get(reverse("backoffice:vehicles")).status_code == 200
    assert client.get(reverse("backoffice:vehicle_create")).status_code == 200
    assert client.get(reverse("backoffice:vehicle_detail", args=[visible.id])).status_code == 200
    assert client.get(reverse("backoffice:vehicle_detail", args=[hidden.id])).status_code == 404

    create_response = client.post(
        reverse("backoffice:vehicle_create"),
        {
            "organization": str(tenant.id),
            "plate": "GGG1H77",
            "vehicle_type": VehicleType.VUC.value,
            "body_type": VehicleBodyType.BAU.value,
            "cargo_profile": VehicleCargoProfile.DRY_CARGO.value,
            "ownership_type": VehicleOwnershipType.OWNED.value,
            "status": VehicleStatus.PENDING_APPROVAL.value,
            "operational_status": VehicleOperationalStatus.UNAVAILABLE.value,
        },
    )
    assert create_response.status_code == 302
    created = Vehicle.objects.get(plate="GGG1H77")
    status_response = client.post(
        reverse("backoffice:vehicle_status", args=[created.id]),
        {"status": VehicleStatus.ACTIVE.value},
    )
    created.refresh_from_db()
    assert status_response.status_code == 302
    assert created.status == VehicleStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_bootstrap_rotta_includes_vehicle_permissions(rbac_ready):
    role = Role.objects.get(code=RoleCode.OPERATIONS_MANAGER)
    assert role.permissions.filter(code=PermissionCode.VEHICLES_CHANGE_STATUS).exists()
    assert role.permissions.filter(code=PermissionCode.VEHICLES_ASSIGN_DRIVER).exists()
    assert role.permissions.filter(code=PermissionCode.VEHICLES_ASSIGN_CARRIER).exists()
    assert role.permissions.filter(code=PermissionCode.VEHICLES_MANAGE_DOCUMENTS).exists()
    assert role.permissions.filter(code=PermissionCode.VEHICLES_MANAGE_REFRIGERATION).exists()
