from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.application.services import (
    CarrierData,
    change_carrier_status,
    create_carrier,
    link_driver,
    link_vehicle,
    unlink_driver,
    unlink_vehicle,
    update_carrier,
)
from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus, CarrierVehicleLinkType
from src.carriers.infrastructure.django.models import (
    CarrierDriverLink,
    CarrierProfile,
    CarrierVehicleLink,
)
from src.drivers.infrastructure.django.models import Driver
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.vehicles.domain.enums import VehicleType
from src.vehicles.infrastructure.django.models import Vehicle


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def tenant():
    return Organization.objects.create(
        name="Rotta 116 Operadora",
        legal_name="Rotta 116 Operadora LTDA",
        document="11222333000181",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_tenant():
    return Organization.objects.create(
        name="Outro Tenant",
        legal_name="Outro Tenant LTDA",
        document="22333444000181",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.mark.django_db(transaction=True)
def test_carrier_service_supports_dry_refrigerated_and_both(tenant, django_user_model):
    actor = django_user_model.objects.create_user(username="carrier-ops", password="safe-pass-123")

    dry = create_carrier(
        data=CarrierData(tenant=tenant, organization=tenant, email="dry@carrier.com"),
        actor=actor,
    )
    refrigerated = create_carrier(
        data=CarrierData(
            tenant=tenant,
            organization=Organization.objects.create(
                name="Frio",
                legal_name="Frio LTDA",
                document="33444555000181",
                type=OrganizationType.TRANSPORT_COMPANY,
            ),
            email="frio@carrier.com",
            cargo_profile=CarrierCargoProfile.REFRIGERATED_CARGO,
        ),
        actor=actor,
    )
    both = create_carrier(
        data=CarrierData(
            tenant=tenant,
            organization=Organization.objects.create(
                name="Hibrida",
                legal_name="Hibrida LTDA",
                document="44555666000181",
                type=OrganizationType.TRANSPORT_COMPANY,
            ),
            email="both@carrier.com",
            cargo_profile=CarrierCargoProfile.BOTH,
            rntrc="12345678",
            rntrc_category="ETC",
        ),
        actor=actor,
    )

    assert dry.cargo_profile == CarrierCargoProfile.DRY_CARGO
    assert refrigerated.cargo_profile == CarrierCargoProfile.REFRIGERATED_CARGO
    assert both.cargo_profile == CarrierCargoProfile.BOTH
    assert AuditLog.objects.filter(
        action="carrier_created",
        target_id=str(both.id),
    ).exists()
    audit = AuditLog.objects.filter(action="carrier_created", target_id=str(both.id)).latest(
        "created_at"
    )
    assert audit.after["rntrc"] == "[REDACTED]"
    assert audit.after["email"] == "[REDACTED]"


@pytest.mark.django_db(transaction=True)
def test_carrier_status_update_owner_and_rntrc_fields(tenant, django_user_model):
    actor = django_user_model.objects.create_user(username="actor", password="safe-pass-123")
    owner = django_user_model.objects.create_user(username="owner", password="safe-pass-123")
    carrier = create_carrier(
        data=CarrierData(
            tenant=tenant,
            organization=tenant,
            email="carrier@rotta.com",
            rntrc="55667788",
            rntrc_status="ATIVO",
        ),
        actor=actor,
    )

    update_carrier(
        carrier,
        actor=actor,
        trade_name="Carrier Atualizada",
        cargo_profile=CarrierCargoProfile.BOTH,
        owner=owner,
        rntrc_category="CTC",
    )
    change_carrier_status(carrier, status=CarrierStatus.ACTIVE, actor=actor)
    carrier.refresh_from_db()

    assert carrier.trade_name == "Carrier Atualizada"
    assert carrier.cargo_profile == CarrierCargoProfile.BOTH
    assert carrier.owner == owner
    assert carrier.status == CarrierStatus.ACTIVE
    assert AuditLog.objects.filter(
        action="carrier_updated",
        target_id=str(carrier.id),
    ).exists()
    assert AuditLog.objects.filter(
        action="carrier_status_changed", target_id=str(carrier.id)
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_carrier_relationships_link_driver_and_vehicle(tenant, other_tenant, django_user_model):
    actor = django_user_model.objects.create_user(username="linker", password="safe-pass-123")
    carrier = create_carrier(
        data=CarrierData(tenant=tenant, organization=tenant, email="carrier@rotta.com"),
        actor=actor,
    )
    driver = Driver.objects.create(organization=tenant, full_name="Motorista Vinculado")
    vehicle = Vehicle.objects.create(
        organization=tenant, plate="CAR1234", vehicle_type=VehicleType.VAN
    )
    outsider_driver = Driver.objects.create(
        organization=other_tenant, full_name="Motorista Externo"
    )

    driver_link = link_driver(carrier=carrier, driver=driver, actor=actor)
    vehicle_link = link_vehicle(
        carrier=carrier,
        vehicle=vehicle,
        link_type=CarrierVehicleLinkType.SUBCONTRACTED,
        actor=actor,
    )
    unlink_driver(driver_link, actor=actor)
    unlink_vehicle(vehicle_link, actor=actor)

    assert not CarrierDriverLink.objects.get(pk=driver_link.pk).active
    assert not CarrierVehicleLink.objects.get(pk=vehicle_link.pk).active
    assert AuditLog.objects.filter(
        action="carrier_driver_linked", target_id=str(driver_link.id)
    ).exists()
    assert AuditLog.objects.filter(
        action="carrier_vehicle_unlinked", target_id=str(vehicle_link.id)
    ).exists()

    with pytest.raises(ValidationError):
        link_driver(carrier=carrier, driver=outsider_driver, actor=actor)


@pytest.mark.django_db
def test_backoffice_carriers_rbac_multitenancy_and_idor(
    client, django_user_model, rbac_ready, tenant, other_tenant
):
    admin_user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    viewer = django_user_model.objects.create_user(username="viewer", password="safe-pass-123")
    grant(admin_user, tenant, RoleCode.COMPANY_ADMIN, AccessScope.COMPANY)
    grant(viewer, tenant, RoleCode.VIEWER, AccessScope.COMPANY)

    visible = CarrierProfile.objects.create(
        tenant=tenant,
        organization=tenant,
        email="visible@carrier.com",
        trade_name="Carrier Visivel",
    )
    hidden = CarrierProfile.objects.create(
        tenant=other_tenant,
        organization=other_tenant,
        email="hidden@carrier.com",
        trade_name="Carrier Oculta",
    )

    anonymous = client.get(reverse("backoffice:carriers"))
    assert anonymous.status_code == 302
    assert anonymous["Location"].startswith(reverse("backoffice:login"))

    client.force_login(viewer)
    assert client.get(reverse("backoffice:carrier_create")).status_code == 403

    client.force_login(admin_user)
    assert client.get(reverse("backoffice:carriers")).status_code == 200
    assert client.get(reverse("backoffice:carrier_create")).status_code == 200
    detail = client.get(reverse("backoffice:carrier_detail", args=[visible.id]))
    idor = client.get(reverse("backoffice:carrier_detail", args=[hidden.id]))
    assert detail.status_code == 200
    assert idor.status_code == 404

    status_response = client.post(
        reverse("backoffice:carrier_status", args=[visible.id]),
        {"action": CarrierStatus.ACTIVE.value},
    )
    visible.refresh_from_db()
    assert status_response.status_code == 302
    assert visible.status == CarrierStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_bootstrap_rotta_creates_carrier_permissions(rbac_ready):
    role = Role.objects.get(code=RoleCode.OPERATIONS_MANAGER)

    assert role.permissions.filter(code=PermissionCode.CARRIERS_VIEW).exists()
    assert role.permissions.filter(code=PermissionCode.CARRIERS_CHANGE_STATUS).exists()
    assert role.permissions.filter(code=PermissionCode.CARRIERS_MANAGE_VEHICLES).exists()
