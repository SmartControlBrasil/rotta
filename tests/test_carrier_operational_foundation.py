import pytest
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.utils import timezone
from django.core.exceptions import ValidationError

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.domain.enums import OperationStatus
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
from src.carriers.infrastructure.django.models import (
    CarrierProfile,
    CarrierDriverLink,
    CarrierVehicleLink,
)
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle, DriverVehicleAssignment
from src.customers.infrastructure.django.models import Customer
from src.audit.infrastructure.django.models import AuditLog
from src.freights.application.operation_services import (
    assign_carrier_driver_to_operation,
    assign_carrier_vehicle_to_operation,
    carrier_operations_visible_to,
)


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
def org_carrier_a(db):
    return Organization.objects.create(name="Carrier Org A", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def org_carrier_b(db):
    return Organization.objects.create(name="Carrier Org B", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def user_carrier_a(db, django_user_model):
    return django_user_model.objects.create_user(username="user_carrier_a", password="password")


@pytest.fixture
def user_carrier_b(db, django_user_model):
    return django_user_model.objects.create_user(username="user_carrier_b", password="password")


@pytest.fixture
def carrier_profile_a(db, org_carrier_a):
    return CarrierProfile.objects.create(
        organization=org_carrier_a,
        tenant=org_carrier_a,
        trade_name="Carrier A",
        email="carrier_a@example.com",
        status="ACTIVE",
    )


@pytest.fixture
def carrier_profile_b(db, org_carrier_b):
    return CarrierProfile.objects.create(
        organization=org_carrier_b,
        tenant=org_carrier_b,
        trade_name="Carrier B",
        email="carrier_b@example.com",
        status="ACTIVE",
    )


@pytest.fixture
def driver_a(db, org_carrier_a):
    return Driver.objects.create(
        organization=org_carrier_a,
        full_name="Driver A",
        status="ACTIVE",
    )


@pytest.fixture
def driver_b(db, org_carrier_b):
    return Driver.objects.create(
        organization=org_carrier_b,
        full_name="Driver B",
        status="ACTIVE",
    )


@pytest.fixture
def vehicle_a(db, org_carrier_a):
    return Vehicle.objects.create(
        organization=org_carrier_a,
        plate="AAA1A11",
        vehicle_type="CAR",
        status="ACTIVE",
    )


@pytest.fixture
def vehicle_b(db, org_carrier_b):
    return Vehicle.objects.create(
        organization=org_carrier_b,
        plate="BBB2B22",
        vehicle_type="CAR",
        status="ACTIVE",
    )


def create_operation_helper(organization, creator, carrier, ref):
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
        created_by=creator,
        owner=creator,
        reference_code=f"REQ-{ref}",
        status="SUBMITTED",
    )
    FreightRequestStop.objects.create(
        freight_request=request,
        sequence=1,
        stop_type="PICKUP",
        city="Cidade Origem",
        state="SP",
        scheduled_date=timezone.now().date(),
    )
    FreightRequestStop.objects.create(
        freight_request=request,
        sequence=2,
        stop_type="DELIVERY",
        city="Cidade Destino",
        state="SP",
        scheduled_date=timezone.now().date(),
    )
    FreightRequestCargo.objects.create(
        freight_request=request,
        description="Cargo Desc",
        cargo_type="GENERAL_CARGO",
        cargo_profile="DRY_CARGO",
        weight_kg=Decimal("1000.0"),
    )
    quote = FreightQuote.objects.create(
        organization=organization,
        freight_request=request,
        created_by=creator,
        owner=creator,
        reference_code=f"QT-{ref}",
    )
    offer = FreightOffer.objects.create(
        organization=organization,
        freight_request=request,
        freight_quote=quote,
        created_by=creator,
        owner=creator,
        reference_code=f"OFR-{ref}",
        status="PUBLISHED",
    )
    interest = FreightOfferInterest.objects.create(
        organization=organization,
        offer=offer,
        carrier=carrier,
        status="ACTIVE",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest,
        organization=organization,
        offer=offer,
        status="CONFIRMED",
        selected_by=creator,
        selected_at=timezone.now(),
    )
    operation = FreightOperation.objects.create(
        organization=organization,
        selection=selection,
        carrier=carrier,
        status=OperationStatus.ASSIGNED.value,
        assigned_at=timezone.now(),
    )
    return operation


@pytest.fixture
def operation_a(db, org_carrier_a, user_carrier_a, carrier_profile_a):
    return create_operation_helper(org_carrier_a, user_carrier_a, carrier_profile_a, "A")


@pytest.fixture
def operation_b(db, org_carrier_b, user_carrier_b, carrier_profile_b):
    return create_operation_helper(org_carrier_b, user_carrier_b, carrier_profile_b, "B")


@pytest.mark.django_db(transaction=True)
def test_carrier_operations_visibility(
    org_carrier_a,
    org_carrier_b,
    user_carrier_a,
    user_carrier_b,
    operation_a,
    operation_b,
    rbac_ready,
):
    grant(user_carrier_a, org_carrier_a, RoleCode.OPERATIONS_MANAGER.value)
    grant(user_carrier_b, org_carrier_b, RoleCode.OPERATIONS_MANAGER.value)

    # Carrier A visibility
    ops_a = carrier_operations_visible_to(user_carrier_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert operation_a in ops_a
    assert operation_b not in ops_a

    # Carrier B visibility
    ops_b = carrier_operations_visible_to(user_carrier_b, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert operation_b in ops_b
    assert operation_a not in ops_b


@pytest.mark.django_db(transaction=True)
def test_driver_assignment_success_and_failures(
    org_carrier_a,
    org_carrier_b,
    user_carrier_a,
    user_carrier_b,
    carrier_profile_a,
    carrier_profile_b,
    driver_a,
    driver_b,
    operation_a,
    rbac_ready,
):
    grant(user_carrier_a, org_carrier_a, RoleCode.OPERATIONS_MANAGER.value)
    grant(user_carrier_b, org_carrier_b, RoleCode.OPERATIONS_MANAGER.value)

    # Establish Carrier -> Driver Links
    CarrierDriverLink.objects.create(carrier=carrier_profile_a, driver=driver_a, active=True)
    CarrierDriverLink.objects.create(carrier=carrier_profile_b, driver=driver_b, active=True)

    # 1. Success assignment
    op = assign_carrier_driver_to_operation(
        actor=user_carrier_a,
        operation_id=operation_a.id,
        driver_id=driver_a.id,
    )
    assert op.driver == driver_a

    # Check AuditLog
    log = AuditLog.objects.filter(target_id=str(operation_a.id)).first()
    assert log is not None
    assert log.action == "driver_assigned"
    assert log.actor == user_carrier_a

    # 2. Inactive Driver link rejection
    inactive_driver = Driver.objects.create(
        organization=org_carrier_a,
        full_name="Driver Inactive Link",
        status="ACTIVE",
    )
    CarrierDriverLink.objects.create(carrier=carrier_profile_a, driver=inactive_driver, active=False)
    with pytest.raises(ValidationError, match="não está vinculado"):
        assign_carrier_driver_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            driver_id=inactive_driver.id,
        )

    # 3. Cross-tenant assignment rejection (Carrier A assigns Driver B)
    with pytest.raises(ValidationError, match="não está vinculado"):
        assign_carrier_driver_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            driver_id=driver_b.id,
        )

    # 4. Cross-tenant actor IDOR (Carrier B tries to assign Driver A to Operation A)
    with pytest.raises(ValidationError, match="Acesso negado"):
        assign_carrier_driver_to_operation(
            actor=user_carrier_b,
            operation_id=operation_a.id,
            driver_id=driver_a.id,
        )


@pytest.mark.django_db(transaction=True)
def test_vehicle_assignment_success_and_failures(
    org_carrier_a,
    org_carrier_b,
    user_carrier_a,
    user_carrier_b,
    carrier_profile_a,
    carrier_profile_b,
    vehicle_a,
    vehicle_b,
    operation_a,
    rbac_ready,
):
    grant(user_carrier_a, org_carrier_a, RoleCode.OPERATIONS_MANAGER.value)
    grant(user_carrier_b, org_carrier_b, RoleCode.OPERATIONS_MANAGER.value)

    # Establish Carrier -> Vehicle Links
    CarrierVehicleLink.objects.create(carrier=carrier_profile_a, vehicle=vehicle_a, active=True)
    CarrierVehicleLink.objects.create(carrier=carrier_profile_b, vehicle=vehicle_b, active=True)

    # 1. Success assignment
    op = assign_carrier_vehicle_to_operation(
        actor=user_carrier_a,
        operation_id=operation_a.id,
        vehicle_id=vehicle_a.id,
    )
    assert op.vehicle == vehicle_a

    # Check AuditLog
    log = AuditLog.objects.filter(target_id=str(operation_a.id), action="vehicle_assigned").first()
    assert log is not None
    assert log.actor == user_carrier_a

    # 2. Cross-tenant vehicle rejection (Carrier A assigns Vehicle B)
    with pytest.raises(ValidationError, match="Veículo não está vinculado"):
        assign_carrier_vehicle_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            vehicle_id=vehicle_b.id,
        )


@pytest.mark.django_db(transaction=True)
def test_driver_vehicle_assignment_compatibility(
    org_carrier_a,
    user_carrier_a,
    carrier_profile_a,
    driver_a,
    vehicle_a,
    operation_a,
    rbac_ready,
):
    grant(user_carrier_a, org_carrier_a, RoleCode.OPERATIONS_MANAGER.value)
    CarrierDriverLink.objects.create(carrier=carrier_profile_a, driver=driver_a, active=True)
    CarrierVehicleLink.objects.create(carrier=carrier_profile_a, vehicle=vehicle_a, active=True)

    # Vehicle Y that is incompatible
    vehicle_y = Vehicle.objects.create(
        organization=org_carrier_a,
        plate="YYY9Y99",
        vehicle_type="CAR",
        status="ACTIVE",
    )
    CarrierVehicleLink.objects.create(carrier=carrier_profile_a, vehicle=vehicle_y, active=True)

    # Driver A has active primary assignment to Vehicle A
    DriverVehicleAssignment.objects.create(
        driver=driver_a,
        vehicle=vehicle_a,
        active=True,
        primary=True,
        valid_from=timezone.now().date(),
    )

    # 1. Assign driver_a to operation having vehicle_y (incompatible) -> Should reject
    operation_a.vehicle = vehicle_y
    operation_a.save()

    with pytest.raises(ValidationError, match="vínculo incompatível"):
        assign_carrier_driver_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            driver_id=driver_a.id,
        )

    # 2. Assign vehicle_y to operation having driver_a (incompatible) -> Should reject
    operation_a.vehicle = None
    operation_a.driver = driver_a
    operation_a.save()

    with pytest.raises(ValidationError, match="incompatível com o motorista"):
        assign_carrier_vehicle_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            vehicle_id=vehicle_y.id,
        )


@pytest.mark.django_db(transaction=True)
def test_operation_final_state_rejection(
    org_carrier_a,
    user_carrier_a,
    carrier_profile_a,
    driver_a,
    vehicle_a,
    operation_a,
    rbac_ready,
):
    grant(user_carrier_a, org_carrier_a, RoleCode.OPERATIONS_MANAGER.value)
    CarrierDriverLink.objects.create(carrier=carrier_profile_a, driver=driver_a, active=True)
    CarrierVehicleLink.objects.create(carrier=carrier_profile_a, vehicle=vehicle_a, active=True)

    # Transition operation to DELIVERED
    operation_a.status = OperationStatus.DELIVERED.value
    operation_a.save()

    # Reassigning driver in final state should reject
    with pytest.raises(ValidationError, match="Não é possível alterar motorista em uma operação finalizada"):
        assign_carrier_driver_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            driver_id=driver_a.id,
        )

    # Reassigning vehicle in final state should reject
    with pytest.raises(ValidationError, match="Não é possível alterar veículo em uma operação finalizada"):
        assign_carrier_vehicle_to_operation(
            actor=user_carrier_a,
            operation_id=operation_a.id,
            vehicle_id=vehicle_a.id,
        )
