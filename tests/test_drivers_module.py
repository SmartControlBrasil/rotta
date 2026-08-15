from datetime import timedelta
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.application.services import CarrierData, create_carrier
from src.drivers.application.services import (
    DriverData,
    change_driver_status,
    link_driver_to_carrier,
    register_driver,
    unlink_driver_from_carrier,
    update_driver,
)
from src.drivers.domain.enums import DriverEngagementType, DriverStatus
from src.drivers.infrastructure.django.models import Driver
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def tenant():
    return Organization.objects.create(
        name="Rotta Tenant",
        legal_name="Rotta Tenant LTDA",
        document="11222333000181",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_tenant():
    return Organization.objects.create(
        name="Outra Operadora",
        legal_name="Outra Operadora LTDA",
        document="22333444000181",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.mark.django_db(transaction=True)
def test_driver_cpf_validation_and_normalization(tenant):
    driver = Driver(
        organization=tenant,
        full_name="Motorista CPF",
        document="111.444.777-35",
    )
    driver.full_clean()
    driver.save()
    assert driver.document == "11144477735"
    assert driver.masked_document == "111.***.***-35"

    invalid = Driver(
        organization=tenant,
        full_name="Inválido",
        document="111.444.777-00",
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()


@pytest.mark.django_db(transaction=True)
def test_driver_service_crud_status_and_audit(tenant, django_user_model):
    actor = django_user_model.objects.create_user(username="driver-actor", password="safe-pass-123")
    driver = register_driver(
        data=DriverData(
            organization=tenant,
            full_name="João da Estrada",
            document="111.444.777-35",
            email="driver@rotta.com",
            driver_license_number="CNH123",
            driver_license_category="D",
            driver_license_expiration=timezone.localdate() + timedelta(days=120),
            engagement_type=DriverEngagementType.AGGREGATED,
        ),
        actor=actor,
    )
    update_driver(
        driver,
        actor=actor,
        mobile_phone="11999998888",
        city="São Paulo",
        state="SP",
    )
    change_driver_status(driver, status=DriverStatus.ACTIVE, actor=actor, reason="onboarding")
    driver.refresh_from_db()
    assert driver.status == DriverStatus.ACTIVE
    assert driver.city == "São Paulo"
    assert AuditLog.objects.filter(action="driver_created", target_id=str(driver.id)).exists()
    assert AuditLog.objects.filter(action="driver_updated", target_id=str(driver.id)).exists()
    status_log = AuditLog.objects.filter(
        action="driver_status_changed", target_id=str(driver.id)
    ).latest("created_at")
    assert status_log.after["document"] == "[REDACTED]"
    assert status_log.after["driver_license_number"] == "[REDACTED]"
    assert status_log.after["email"] == "[REDACTED]"


@pytest.mark.django_db(transaction=True)
def test_driver_carrier_link_records_audit(tenant, django_user_model):
    actor = django_user_model.objects.create_user(username="carrier-link", password="safe-pass-123")
    carrier = create_carrier(
        data=CarrierData(
            tenant=tenant,
            organization=tenant,
            email="carrier@rotta.com",
        ),
        actor=actor,
    )
    driver = register_driver(
        data=DriverData(
            organization=tenant,
            full_name="Motorista Carrier",
            document="111.444.777-35",
            engagement_type=DriverEngagementType.CARRIER,
        ),
        actor=actor,
    )
    link = link_driver_to_carrier(driver=driver, carrier=carrier, actor=actor)
    unlink_driver_from_carrier(link, actor=actor)
    assert AuditLog.objects.filter(action="driver_carrier_linked", target_id=str(link.id)).exists()
    assert AuditLog.objects.filter(
        action="driver_carrier_unlinked", target_id=str(link.id)
    ).exists()


@pytest.mark.django_db
def test_backoffice_driver_routes_rbac_and_idor(
    client, django_user_model, rbac_ready, tenant, other_tenant
):
    manager = django_user_model.objects.create_user(username="manager", password="safe-pass-123")
    outsider = django_user_model.objects.create_user(username="outsider", password="safe-pass-123")
    grant(manager, tenant, RoleCode.OPERATIONS_MANAGER, AccessScope.COMPANY)
    grant(outsider, tenant, RoleCode.VIEWER, AccessScope.COMPANY)

    in_scope = Driver.objects.create(
        organization=tenant,
        full_name="Escopo",
        document="11144477735",
        driver_license_number="CNH1",
    )
    out_scope = Driver.objects.create(
        organization=other_tenant,
        full_name="Fora Escopo",
        document="98765432100",
        driver_license_number="CNH2",
    )

    anon = client.get(reverse("backoffice:drivers"))
    assert anon.status_code == 302

    client.force_login(outsider)
    assert client.get(reverse("backoffice:driver_create")).status_code == 403

    client.force_login(manager)
    assert client.get(reverse("backoffice:drivers")).status_code == 200
    assert client.get(reverse("backoffice:driver_create")).status_code == 200
    assert client.get(reverse("backoffice:driver_detail", args=[in_scope.id])).status_code == 200
    assert client.get(reverse("backoffice:driver_detail", args=[out_scope.id])).status_code == 404

    create_response = client.post(
        reverse("backoffice:driver_create"),
        {
            "organization": str(tenant.id),
            "full_name": "Novo Motorista",
            "document": "",
            "engagement_type": DriverEngagementType.OWNED.value,
            "country": "BR",
            "status": DriverStatus.PENDING.value,
            "availability_status": "OFFLINE",
        },
    )
    assert create_response.status_code == 302
    created = Driver.objects.get(full_name="Novo Motorista")
    edit_response = client.post(
        reverse("backoffice:driver_edit", args=[created.id]),
        {
            "organization": str(tenant.id),
            "full_name": "Novo Motorista Editado",
            "document": "",
            "engagement_type": DriverEngagementType.PARTNER.value,
            "country": "BR",
            "status": DriverStatus.PENDING.value,
            "availability_status": "OFFLINE",
        },
    )
    assert edit_response.status_code == 302

    status_response = client.post(
        reverse("backoffice:driver_status", args=[created.id]),
        {"status": DriverStatus.ACTIVE.value},
    )
    created.refresh_from_db()
    assert status_response.status_code == 302
    assert created.status == DriverStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_bootstrap_rotta_adds_new_driver_permissions(rbac_ready):
    role = Role.objects.get(code=RoleCode.OPERATIONS_MANAGER)
    assert role.permissions.filter(code=PermissionCode.DRIVERS_CHANGE_STATUS).exists()
    assert role.permissions.filter(code=PermissionCode.DRIVERS_MANAGE_DOCUMENTS).exists()
    assert role.permissions.filter(code=PermissionCode.DRIVERS_ASSIGN_VEHICLE).exists()
    assert role.permissions.filter(code=PermissionCode.DRIVERS_ASSIGN_CARRIER).exists()
