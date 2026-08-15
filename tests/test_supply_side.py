from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from src.audit.infrastructure.django.models import AuditLog
from src.drivers.application.services import (
    DriverData,
    add_driver_document,
    approve_driver,
    register_driver,
    verify_driver_document,
)
from src.drivers.domain.enums import (
    DriverApprovalStatus,
    DriverAvailabilityStatus,
    DriverDocumentType,
)
from src.drivers.infrastructure.django.models import Driver
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.infrastructure.django.storage import PrivateDocumentStorageAdapter
from src.vehicles.application.services import (
    VehicleData,
    assign_driver_to_vehicle,
    register_vehicle,
    unassign_driver_vehicle,
)
from src.vehicles.domain.enums import VehicleOwnershipType, VehicleStatus, VehicleType
from src.vehicles.infrastructure.django.models import DriverVehicleAssignment, Vehicle


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Rotta 116 Provider",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization():
    return Organization.objects.create(
        name="Outro Provider",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.mark.django_db(transaction=True)
def test_driver_is_business_entity_not_user(django_user_model, organization):
    user = django_user_model.objects.create_user(username="driver-user", password="safe-pass-123")

    driver = register_driver(
        data=DriverData(
            organization=organization,
            user=user,
            full_name="Ana Motorista",
            phone="11999990000",
            document="11144477735",
        ),
        actor=user,
    )

    assert driver.user == user
    assert driver.full_name != user.username
    assert driver.approval_status == DriverApprovalStatus.PENDING
    assert driver.availability_status == DriverAvailabilityStatus.OFFLINE
    assert AuditLog.objects.filter(action="driver_created", target_id=str(driver.id)).exists()


@pytest.mark.django_db(transaction=True)
def test_expired_driver_license_cannot_be_approved(django_user_model, organization):
    actor = django_user_model.objects.create_user(username="approver", password="safe-pass-123")
    driver = Driver.objects.create(
        organization=organization,
        full_name="CNH Vencida",
        driver_license_expiration=timezone.localdate() - timedelta(days=1),
    )

    with pytest.raises(ValidationError):
        approve_driver(driver, actor=actor)


@pytest.mark.django_db(transaction=True)
def test_driver_document_uses_private_storage_and_redacts_audit(
    django_user_model, organization, tmp_path, settings
):
    settings.PRIVATE_DOCUMENT_STORAGE_ROOT = tmp_path
    actor = django_user_model.objects.create_user(username="docs", password="safe-pass-123")
    driver = Driver.objects.create(organization=organization, full_name="Documento Seguro")
    storage = PrivateDocumentStorageAdapter()

    document = add_driver_document(
        driver=driver,
        document_type=DriverDocumentType.DRIVER_LICENSE,
        storage=storage,
        content=BytesIO(b"private-cnh"),
        filename="cnh.txt",
        actor=actor,
        expiration_date=timezone.localdate() + timedelta(days=30),
    )
    verify_driver_document(document, actor=actor)

    assert storage.exists(document.storage_key)
    assert document.status == "APPROVED"
    audit = AuditLog.objects.filter(action="document_uploaded").latest("created_at")
    assert audit.after["storage_key"] == "[REDACTED]"
    assert "private-cnh" not in str(audit.after)


@pytest.mark.django_db(transaction=True)
def test_vehicle_plate_is_normalized_and_capacity_must_be_non_negative(organization):
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate="abc-1d23",
            vehicle_type=VehicleType.VAN,
            ownership_type=VehicleOwnershipType.AGGREGATED,
            capacity_weight_kg=Decimal("1200.50"),
            closed_box=True,
        )
    )

    assert vehicle.plate == "ABC1D23"
    assert vehicle.closed_box
    invalid = Vehicle(
        organization=organization,
        plate="NEG1234",
        vehicle_type=VehicleType.CARRO,
        capacity_weight_kg=Decimal("-1"),
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()


@pytest.mark.django_db(transaction=True)
def test_vehicle_plate_is_unique_inside_provider_scope(organization):
    Vehicle.objects.create(
        organization=organization, plate="ABC1D23", vehicle_type=VehicleType.CARRO
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Vehicle.objects.create(
            organization=organization, plate="ABC1D23", vehicle_type=VehicleType.VAN
        )


@pytest.mark.django_db(transaction=True)
def test_driver_vehicle_assignment_rules(django_user_model, organization, other_organization):
    actor = django_user_model.objects.create_user(username="ops", password="safe-pass-123")
    driver = Driver.objects.create(organization=organization, full_name="João")
    vehicle = Vehicle.objects.create(
        organization=organization,
        plate="AAA1A11",
        vehicle_type=VehicleType.MOTO,
        status=VehicleStatus.ACTIVE,
    )
    other_vehicle = Vehicle.objects.create(
        organization=other_organization,
        plate="BBB2B22",
        vehicle_type=VehicleType.CARRO,
    )

    assignment = assign_driver_to_vehicle(
        driver=driver,
        vehicle=vehicle,
        valid_from=date.today(),
        actor=actor,
        primary=True,
    )
    unassign_driver_vehicle(assignment, valid_until=date.today(), actor=actor)

    invalid = DriverVehicleAssignment(
        driver=driver,
        vehicle=other_vehicle,
        valid_from=date.today(),
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()
    assert AuditLog.objects.filter(action="driver_vehicle_assigned").exists()
    assert AuditLog.objects.filter(action="driver_vehicle_unassigned").exists()


@pytest.mark.django_db(transaction=True)
def test_bootstrap_rotta_creates_supply_side_permissions(rbac_ready):
    role = Role.objects.get(code=RoleCode.OPERATIONS_MANAGER)

    assert role.permissions.filter(code=PermissionCode.DRIVERS_VIEW).exists()
    assert role.permissions.filter(code=PermissionCode.DRIVERS_APPROVE).exists()
    assert role.permissions.filter(code=PermissionCode.VEHICLES_VIEW).exists()


@pytest.mark.django_db
def test_backoffice_drivers_and_vehicles_require_permission(client, django_user_model):
    user = django_user_model.objects.create_user(username="plain", password="safe-pass-123")
    client.force_login(user)

    assert client.get(reverse("backoffice:drivers")).status_code == 403
    assert client.get(reverse("backoffice:vehicles")).status_code == 403


@pytest.mark.django_db
def test_backoffice_supply_side_lists_details_filters_and_scope(
    client, django_user_model, rbac_ready, organization, other_organization
):
    user = django_user_model.objects.create_user(username="manager", password="safe-pass-123")
    grant(user, organization, RoleCode.OPERATIONS_MANAGER)
    visible_driver = Driver.objects.create(
        organization=organization,
        full_name="Visível",
        approval_status=DriverApprovalStatus.PENDING,
        availability_status=DriverAvailabilityStatus.AVAILABLE,
    )
    hidden_driver = Driver.objects.create(organization=other_organization, full_name="Oculto")
    vehicle = Vehicle.objects.create(
        organization=organization,
        plate="VIS1B23",
        vehicle_type=VehicleType.VUC,
        brand="Marca",
        model="Modelo",
    )
    hidden_vehicle = Vehicle.objects.create(
        organization=other_organization,
        plate="HID1B23",
        vehicle_type=VehicleType.CARRO,
    )
    DriverVehicleAssignment.objects.create(
        driver=visible_driver,
        vehicle=vehicle,
        valid_from=date.today(),
        active=True,
        primary=True,
    )
    client.force_login(user)

    drivers = client.get(reverse("backoffice:drivers"), {"q": "Vis"})
    vehicles = client.get(reverse("backoffice:vehicles"), {"plate": "VIS"})
    driver_detail = client.get(reverse("backoffice:driver_detail", args=[visible_driver.id]))
    vehicle_detail = client.get(reverse("backoffice:vehicle_detail", args=[vehicle.id]))

    assert drivers.status_code == 200
    assert "Visível".encode() in drivers.content
    assert b"Oculto" not in drivers.content
    assert vehicles.status_code == 200
    assert b"VIS1B23" in vehicles.content
    assert b"HID1B23" not in vehicles.content
    assert driver_detail.status_code == 200
    assert vehicle_detail.status_code == 200
    hidden_driver_detail = client.get(reverse("backoffice:driver_detail", args=[hidden_driver.id]))
    assert hidden_driver_detail.status_code == 404
    hidden_vehicle_detail = client.get(
        reverse("backoffice:vehicle_detail", args=[hidden_vehicle.id])
    )
    assert hidden_vehicle_detail.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_backoffice_driver_approval_action_is_rbac_controlled(
    client, django_user_model, rbac_ready, organization
):
    approver = django_user_model.objects.create_user(username="approver", password="safe-pass-123")
    viewer = django_user_model.objects.create_user(username="viewer", password="safe-pass-123")
    grant(approver, organization, RoleCode.OPERATIONS_MANAGER)
    grant(viewer, organization, RoleCode.DISPATCHER)
    driver = Driver.objects.create(
        organization=organization,
        full_name="Aprovar",
        driver_license_expiration=timezone.localdate() + timedelta(days=30),
    )

    client.force_login(viewer)
    forbidden = client.post(
        reverse("backoffice:driver_detail", args=[driver.id]), {"action": "approve"}
    )
    assert forbidden.status_code == 403

    client.force_login(approver)
    response = client.post(
        reverse("backoffice:driver_detail", args=[driver.id]), {"action": "approve"}
    )
    driver.refresh_from_db()

    assert response.status_code == 302
    assert driver.approval_status == DriverApprovalStatus.APPROVED
    assert AuditLog.objects.filter(action="driver_approved", target_id=str(driver.id)).exists()


@pytest.mark.django_db
def test_backoffice_supply_side_pagination(client, django_user_model, rbac_ready, organization):
    user = django_user_model.objects.create_user(username="pager", password="safe-pass-123")
    grant(user, organization, RoleCode.OPERATIONS_MANAGER, AccessScope.ALL)
    for index in range(30):
        Driver.objects.create(organization=organization, full_name=f"Motorista {index:02d}")
    client.force_login(user)

    response = client.get(reverse("backoffice:drivers"))

    assert response.status_code == 200
    assert b"1 / 2" in response.content
