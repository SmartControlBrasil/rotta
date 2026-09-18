import datetime
import threading
from io import StringIO
import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import IntegrityError, transaction

from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer
from src.freights.domain.enums import (
    ContractedRouteStatus,
    ContractedRouteOccurrenceStatus,
    OperationSource,
    OperationStatus,
    RouteWeekday,
)
from src.freights.infrastructure.django.models import (
    ContractedRoute,
    ContractedRouteWeekday,
    ContractedRouteStop,
    ContractedRouteOccurrence,
    FreightOperation,
    FreightOperationStop,
)
from src.freights.application.route_services import (
    create_contracted_route_occurrence,
    materialize_contracted_route_occurrence,
)
from src.freights.application.operation_services import (
    change_operation_status,
    change_stop_status,
    report_operation_incident,
    record_proof_of_delivery,
)
from src.freights.application.tracking_services import (
    start_tracking_session,
    record_location_point,
)
from src.identity.infrastructure.django.models import Role, MembershipRole

def grant_permission_to_user(user, org, role_code):
    role = Role.objects.get(code=role_code)
    membership, _ = Membership.objects.get_or_create(user=user, organization=org, defaults={"status": "ACTIVE"})
    MembershipRole.objects.get_or_create(membership=membership, role=role)

@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())

# =========================================================================
# Multi-Tenant Real Fixtures (Distinguishing Carrier and Shipper Organizations)
# =========================================================================

@pytest.fixture
def org_shipper_a(db):
    return Organization.objects.create(name="ShipperOrgA", type=OrganizationType.CUSTOMER)

@pytest.fixture
def org_shipper_b(db):
    return Organization.objects.create(name="ShipperOrgB", type=OrganizationType.CUSTOMER)

@pytest.fixture
def org_carrier_x(db):
    return Organization.objects.create(name="CarrierOrgX", type=OrganizationType.TRANSPORT_COMPANY)

@pytest.fixture
def org_carrier_y(db):
    return Organization.objects.create(name="CarrierOrgY", type=OrganizationType.TRANSPORT_COMPANY)

@pytest.fixture
def customer_of_shipper_a(db, org_shipper_a):
    return Customer.objects.create(
        organization=org_shipper_a,
        legal_name="Customer of Shipper A",
        document_number="11111111111",
        email="cust_a@example.com",
    )

@pytest.fixture
def customer_of_shipper_b(db, org_shipper_b):
    return Customer.objects.create(
        organization=org_shipper_b,
        legal_name="Customer of Shipper B",
        document_number="22222222222",
        email="cust_b@example.com",
    )

@pytest.fixture
def carrier_profile_x_under_shipper_a(db, org_carrier_x, org_shipper_a):
    # Registered carrier profile under shipper A's tenant scope
    return CarrierProfile.objects.create(
        organization=org_carrier_x,
        tenant=org_shipper_a,
        trade_name="Carrier X (under Shipper A)",
        email="carrier_x@example.com",
        status="ACTIVE",
    )

@pytest.fixture
def carrier_profile_y_under_shipper_a(db, org_carrier_y, org_shipper_a):
    return CarrierProfile.objects.create(
        organization=org_carrier_y,
        tenant=org_shipper_a,
        trade_name="Carrier Y (under Shipper A)",
        email="carrier_y@example.com",
        status="ACTIVE",
    )

@pytest.fixture
def carrier_profile_x_own(db, org_carrier_x):
    # Carrier profile from the perspective of the carrier's own tenant
    return CarrierProfile.objects.create(
        organization=org_carrier_x,
        tenant=org_carrier_x,
        trade_name="Carrier X (Own Profile)",
        email="carrier_x_own@example.com",
        status="ACTIVE",
    )

@pytest.fixture
def driver_of_carrier_x(db, org_carrier_x):
    User = get_user_model()
    u = User.objects.create_user(username="driver_john", password="password")
    Membership.objects.create(user=u, organization=org_carrier_x, status="ACTIVE")
    return Driver.objects.create(
        organization=org_carrier_x,
        user=u,
        full_name="John Doe",
        status="ACTIVE",
    )

@pytest.fixture
def driver_of_carrier_y(db, org_carrier_y):
    User = get_user_model()
    u = User.objects.create_user(username="driver_bob", password="password")
    Membership.objects.create(user=u, organization=org_carrier_y, status="ACTIVE")
    return Driver.objects.create(
        organization=org_carrier_y,
        user=u,
        full_name="Bob Smith",
        status="ACTIVE",
    )

@pytest.fixture
def vehicle_of_carrier_x(db, org_carrier_x):
    return Vehicle.objects.create(
        organization=org_carrier_x,
        plate="CAR-1111",
        vehicle_type="CAR",
        status="ACTIVE",
    )

@pytest.fixture
def vehicle_of_carrier_y(db, org_carrier_y):
    return Vehicle.objects.create(
        organization=org_carrier_y,
        plate="CAR-2222",
        vehicle_type="CAR",
        status="ACTIVE",
    )

@pytest.fixture
def manager_user_x(db, org_carrier_x):
    User = get_user_model()
    u = User.objects.create_user(username="manager_x", password="password")
    Membership.objects.create(user=u, organization=org_carrier_x, status="ACTIVE")
    return u

@pytest.fixture
def base_route_carrier_perspective(org_carrier_x, customer_of_shipper_a, carrier_profile_x_own):
    route = ContractedRoute.objects.create(
        organization=org_carrier_x,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_x_own,
        name="Rota SP - RJ Recorrente (Carrier)",
        status=ContractedRouteStatus.ACTIVE.value,
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
    )
    ContractedRouteWeekday.objects.create(route=route, day=RouteWeekday.MON.value)
    ContractedRouteWeekday.objects.create(route=route, day=RouteWeekday.WED.value)
    ContractedRouteWeekday.objects.create(route=route, day=RouteWeekday.FRI.value)
    return route


# =========================================================================
# Test Cases
# =========================================================================

# 1. Rota válida na perspectiva contratante (Shipper)
@pytest.mark.django_db
def test_route_valid_shipper_perspective(org_shipper_a, customer_of_shipper_a, carrier_profile_x_under_shipper_a):
    route = ContractedRoute.objects.create(
        organization=org_shipper_a,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_x_under_shipper_a,
        name="Contracted Route - Shipper perspective",
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
    )
    assert route.id is not None
    assert route.clean() is None # passes validation


# 2. Rota válida na perspectiva transportadora (Carrier)
@pytest.mark.django_db
def test_route_valid_carrier_perspective(base_route_carrier_perspective):
    assert base_route_carrier_perspective.id is not None
    assert base_route_carrier_perspective.clean() is None # passes validation


# 3. Carrier de outro tenant rejeitado (Shipper perspective)
@pytest.mark.django_db
def test_carrier_of_another_tenant_rejected(org_shipper_b, customer_of_shipper_b, carrier_profile_x_under_shipper_a):
    # Route belongs to Shipper B, but carrier profile is registered under Shipper A
    route = ContractedRoute(
        organization=org_shipper_b,
        customer=customer_of_shipper_b,
        carrier=carrier_profile_x_under_shipper_a,
        name="Cross tenant carrier check",
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
    )
    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "carrier" in exc.value.error_dict


# 4. Customer privado de outra transportadora rejeitado (Carrier perspective)
@pytest.mark.django_db
def test_customer_private_of_another_carrier_rejected(org_carrier_x, carrier_profile_x_own, org_carrier_y):
    # Customer belongs to a competing carrier company (TRANSPORT_COMPANY)
    private_customer = Customer.objects.create(
        organization=org_carrier_y,
        legal_name="Competing Carrier Private Cust",
        document_number="99999999999",
        email="private@competing.com",
    )
    route = ContractedRoute(
        organization=org_carrier_x,
        customer=private_customer,
        carrier=carrier_profile_x_own,
        name="Cross carrier private customer check",
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
    )
    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "customer" in exc.value.error_dict


# 5. preferred_driver deve pertencer a carrier.organization
@pytest.mark.django_db
def test_preferred_driver_must_belong_to_carrier_organization(org_carrier_x, customer_of_shipper_a, carrier_profile_x_own, driver_of_carrier_y):
    route = ContractedRoute(
        organization=org_carrier_x,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_x_own,
        name="Route driver validation",
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
        preferred_driver=driver_of_carrier_y, # Belongs to Org Y, but carrier profile is Org X
    )
    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "preferred_driver" in exc.value.error_dict


# 6. preferred_vehicle deve pertencer a carrier.organization
@pytest.mark.django_db
def test_preferred_vehicle_must_belong_to_carrier_organization(org_carrier_x, customer_of_shipper_a, carrier_profile_x_own, vehicle_of_carrier_y):
    route = ContractedRoute(
        organization=org_carrier_x,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_x_own,
        name="Route vehicle validation",
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
        preferred_vehicle=vehicle_of_carrier_y, # Belongs to Org Y
    )
    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "preferred_vehicle" in exc.value.error_dict


# 7. ValidationError de negócio em criação concorrente NÃO é engolido
@pytest.mark.django_db
def test_business_validation_error_is_not_swallowed(rbac_ready, base_route_carrier_perspective, manager_user_x, driver_of_carrier_y):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")

    # We pass driver_of_carrier_y, which belongs to Org Y, while the route is Org X.
    # This must raise ValidationError and NOT get swallowed by the concurrency handling.
    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 8, 24),
            driver_id=str(driver_of_carrier_y.id),
            actor=manager_user_x,
        )
    assert "driver" in exc.value.error_dict


# 8. RBAC cross-organization: OPERATIONS_MANAGER em A não pode gerenciar B
@pytest.mark.django_db
def test_rbac_cross_organization_blocked(rbac_ready, base_route_carrier_perspective, org_carrier_y):
    # Create user who is manager of Org Y (A), and also has membership in Org X (B) but no role in Org X
    User = get_user_model()
    manager_y = User.objects.create_user(username="manager_y", password="password")

    # Active manager in Org Y
    grant_permission_to_user(manager_y, org_carrier_y, "OPERATIONS_MANAGER")

    # Membership only in Org X, but NO roles/permissions
    Membership.objects.create(user=manager_y, organization=base_route_carrier_perspective.organization, status="ACTIVE")

    # Creating occurrence for base_route (Org X) should be rejected
    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 8, 24),
            actor=manager_y,
        )
    assert "actor" in exc.value.error_dict


# 9. DRIVER não pode criar ocorrências
@pytest.mark.django_db
def test_driver_cannot_create_occurrence(rbac_ready, base_route_carrier_perspective, driver_of_carrier_x):
    grant_permission_to_user(driver_of_carrier_x.user, base_route_carrier_perspective.organization, "DRIVER")

    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 8, 24),
            actor=driver_of_carrier_x.user,
        )
    assert "actor" in exc.value.error_dict


# 10. DRIVER não pode materializar ocorrências
@pytest.mark.django_db
def test_driver_cannot_materialize_occurrence(rbac_ready, base_route_carrier_perspective, manager_user_x, driver_of_carrier_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    grant_permission_to_user(driver_of_carrier_x.user, base_route_carrier_perspective.organization, "DRIVER")

    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )

    with pytest.raises(ValidationError) as exc:
        materialize_contracted_route_occurrence(
            occurrence_id=str(occ.id),
            actor=driver_of_carrier_x.user,
        )
    assert "actor" in exc.value.error_dict


# 11. vigência inválida (datas inválidas)
@pytest.mark.django_db
def test_invalid_vigencia(org_carrier_x, customer_of_shipper_a, carrier_profile_x_own):
    route = ContractedRoute(
        organization=org_carrier_x,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_x_own,
        name="Invalid Vigência Rota",
        status=ContractedRouteStatus.ACTIVE.value,
        valid_from=datetime.date(2026, 8, 10),
        valid_until=datetime.date(2026, 8, 9),
        load_type="FTL",
    )
    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "valid_until" in exc.value.error_dict


# 12. sequência duplicada de stop
@pytest.mark.django_db
def test_duplicate_stop_sequence(base_route_carrier_perspective, org_carrier_x):
    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )
    with pytest.raises(IntegrityError):
        ContractedRouteStop.objects.create(
            organization=org_carrier_x,
            contracted_route=base_route_carrier_perspective,
            sequence=1,
            stop_type="DELIVERY",
            city="Rio de Janeiro",
            state="RJ",
        )


# 13. rota DRAFT não gera occurrence
@pytest.mark.django_db
def test_draft_route_does_not_generate_occurrence(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    base_route_carrier_perspective.status = ContractedRouteStatus.DRAFT.value
    base_route_carrier_perspective.save()

    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 8, 24), # Mon
            actor=manager_user_x,
        )
    assert "Apenas rotas ativas podem gerar ocorrências" in str(exc.value)


# 14. rota PAUSED não gera occurrence
@pytest.mark.django_db
def test_paused_route_does_not_generate_occurrence(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    base_route_carrier_perspective.status = ContractedRouteStatus.PAUSED.value
    base_route_carrier_perspective.save()

    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 8, 24),
            actor=manager_user_x,
        )
    assert "Apenas rotas ativas" in str(exc.value)


# 15. rota EXPIRED não gera occurrence
@pytest.mark.django_db
def test_expired_route_does_not_generate_occurrence(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 9, 2), # Outside validity period
            actor=manager_user_x,
        )
    assert "Data da ocorrência fora do período de vigência" in str(exc.value)


# 16. weekday inválido
@pytest.mark.django_db
def test_weekday_invalid(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    # 2026-08-25 is a Tuesday (TUE), but base_route operates on MON, WED, FRI
    with pytest.raises(ValidationError) as exc:
        create_contracted_route_occurrence(
            route_id=str(base_route_carrier_perspective.id),
            occurrence_date=datetime.date(2026, 8, 25),
            actor=manager_user_x,
        )
    assert "Rota não opera em um(a) TUE" in str(exc.value)


# 17. occurrence duplicada de forma síncrona
@pytest.mark.django_db
def test_occurrence_duplicate(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    # Re-creating should return the existing one idempotently (concurrency fallback logic)
    occ2 = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    assert occ2 is not None


# 18. preferred_driver válido
@pytest.mark.django_db
def test_preferred_driver_valid(rbac_ready, base_route_carrier_perspective, driver_of_carrier_x, vehicle_of_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    base_route_carrier_perspective.preferred_driver = driver_of_carrier_x
    base_route_carrier_perspective.preferred_vehicle = vehicle_of_carrier_x
    base_route_carrier_perspective.save()

    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    assert occ.driver == driver_of_carrier_x
    assert occ.vehicle == vehicle_of_carrier_x


# 19. occurrence CANCELLED não materializa
@pytest.mark.django_db
def test_cancelled_occurrence_cannot_materialize(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    occ.status = ContractedRouteOccurrenceStatus.CANCELLED.value
    occ.save()

    with pytest.raises(ValidationError) as exc:
        materialize_contracted_route_occurrence(
            occurrence_id=str(occ.id),
            actor=manager_user_x,
        )
    assert "Apenas ocorrências planejadas" in str(exc.value)


# 20. criação concorrente da mesma occurrence
@pytest.mark.django_db(transaction=True)
def test_concurrent_occurrence_creation(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            occ = create_contracted_route_occurrence(
                route_id=str(base_route_carrier_perspective.id),
                occurrence_date=datetime.date(2026, 8, 24),
                actor=manager_user_x,
            )
            results.append(occ.id)
        except Exception as exc:
            errors.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, f"Unexpected errors: {errors}"
    assert len(results) == 2
    assert results[0] == results[1]
    assert ContractedRouteOccurrence.objects.filter(contracted_route=base_route_carrier_perspective, occurrence_date=datetime.date(2026, 8, 24)).count() == 1


# 21. materialização concorrente
@pytest.mark.django_db(transaction=True)
def test_concurrent_materialization(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )

    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            op = materialize_contracted_route_occurrence(
                occurrence_id=str(occ.id),
                actor=manager_user_x,
            )
            results.append(op.id)
        except Exception as exc:
            errors.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, f"Unexpected errors: {errors}"
    assert len(results) == 2
    assert results[0] == results[1]


# 22. snapshot de window_start e window_end
@pytest.mark.django_db
def test_snapshot_window_fields(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    stop = ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
        window_start=datetime.time(8, 30),
        window_end=datetime.time(10, 45),
    )

    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    op = materialize_contracted_route_occurrence(
        occurrence_id=str(occ.id),
        actor=manager_user_x,
    )

    op_stop = op.stops.get(sequence=1)
    assert op_stop.window_start == datetime.time(8, 30)
    assert op_stop.window_end == datetime.time(10, 45)
    assert op_stop.scheduled_date == datetime.date(2026, 8, 24)


# 23. alteração do template não altera operação existente
@pytest.mark.django_db
def test_alteration_after_materialization_does_not_affect(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    stop = ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
        window_start=datetime.time(8, 0),
        window_end=datetime.time(10, 0),
    )

    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    op = materialize_contracted_route_occurrence(
        occurrence_id=str(occ.id),
        actor=manager_user_x,
    )

    # Modify template stops windows
    stop.window_start = datetime.time(11, 0)
    stop.window_end = datetime.time(13, 0)
    stop.save()

    # Materialized operation stops should still have original window start/end
    op_stop = op.stops.get(sequence=1)
    assert op_stop.window_start == datetime.time(8, 0)
    assert op_stop.window_end == datetime.time(10, 0)


# 24. semântica de alteração de preferred_driver/preferred_vehicle entre occurrence e materialização
@pytest.mark.django_db
def test_alteration_between_occurrence_and_materialization(rbac_ready, base_route_carrier_perspective, driver_of_carrier_x, driver_of_carrier_y, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    base_route_carrier_perspective.preferred_driver = driver_of_carrier_x
    base_route_carrier_perspective.save()

    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    assert occ.driver == driver_of_carrier_x

    # Changing route's preferred driver after occurrence creation
    base_route_carrier_perspective.preferred_driver = None
    base_route_carrier_perspective.save()

    # Materialization must respect the occurrence planning (driver remains driver)
    op = materialize_contracted_route_occurrence(
        occurrence_id=str(occ.id),
        actor=manager_user_x,
    )
    assert op.driver == driver_of_carrier_x


# 25. source_type correto
@pytest.mark.django_db
def test_source_type_correct(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    op = materialize_contracted_route_occurrence(
        occurrence_id=str(occ.id),
        actor=manager_user_x,
    )
    assert op.source_type == OperationSource.CONTRACTED_ROUTE.value


# 26. selection NULL
@pytest.mark.django_db
def test_selection_null(rbac_ready, base_route_carrier_perspective, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        actor=manager_user_x,
    )
    op = materialize_contracted_route_occurrence(
        occurrence_id=str(occ.id),
        actor=manager_user_x,
    )
    assert op.selection is None


# 27. marketplace sem regressão
@pytest.mark.django_db
def test_marketplace_continues_working(org_carrier_x, carrier_profile_x_own, driver_of_carrier_x, vehicle_of_carrier_x):
    from src.freights.infrastructure.django.models import FreightOfferSelection
    from tests.test_api_v1_driver_operations import make_operation

    op = make_operation(org_carrier_x, driver_of_carrier_x.user, driver_of_carrier_x, "A")
    assert op.source_type == OperationSource.MARKETPLACE.value
    assert op.selection is not None


# 28. ciclo e2e da viagem materializada
@pytest.mark.django_db
def test_end_to_end_materialized_execution(rbac_ready, base_route_carrier_perspective, org_carrier_x, driver_of_carrier_x, vehicle_of_carrier_x, manager_user_x):
    grant_permission_to_user(driver_of_carrier_x.user, org_carrier_x, "DRIVER")
    grant_permission_to_user(manager_user_x, org_carrier_x, "OPERATIONS_MANAGER")

    stop1 = ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )
    stop2 = ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=2,
        stop_type="DELIVERY",
        city="Rio de Janeiro",
        state="RJ",
    )

    occ = create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=datetime.date(2026, 8, 24),
        driver_id=str(driver_of_carrier_x.id),
        vehicle_id=str(vehicle_of_carrier_x.id),
        actor=manager_user_x,
    )
    op = materialize_contracted_route_occurrence(
        occurrence_id=str(occ.id),
        actor=manager_user_x,
    )

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    session = start_tracking_session(actor=driver_of_carrier_x.user, operation_id=str(op.id))
    assert session is not None
    pt = record_location_point(
        actor=driver_of_carrier_x.user,
        tracking_session_id=str(session.id),
        latitude=-23.5,
        longitude=-46.6,
        accuracy_m=10.0,
    )
    assert pt is not None

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.ARRIVED_AT_PICKUP,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    inc = report_operation_incident(
        operation_id=str(op.id),
        description="Furo no pneu",
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )
    assert inc is not None

    op_stop1 = op.stops.get(sequence=1)
    change_stop_status(
        operation_id=str(op.id),
        stop_id=str(op_stop1.id),
        new_status="ARRIVED",
        actor=driver_of_carrier_x.user,
    )

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.LOADING,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    change_stop_status(
        operation_id=str(op.id),
        stop_id=str(op_stop1.id),
        new_status="COMPLETED",
        actor=driver_of_carrier_x.user,
    )

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.IN_TRANSIT,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    op_stop2 = op.stops.get(sequence=2)
    change_stop_status(
        operation_id=str(op.id),
        stop_id=str(op_stop2.id),
        new_status="ARRIVED",
        actor=driver_of_carrier_x.user,
    )

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.ARRIVED_AT_DELIVERY,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.UNLOADING,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    pod = record_proof_of_delivery(
        operation_id=str(op.id),
        receiver_name="Recebedor RJ",
        delivered_at=timezone.now(),
        actor=driver_of_carrier_x.user,
        driver_only=True,
        stop_id=str(op_stop2.id),
    )
    assert pod is not None

    change_stop_status(
        operation_id=str(op.id),
        stop_id=str(op_stop2.id),
        new_status="COMPLETED",
        actor=driver_of_carrier_x.user,
    )

    change_operation_status(
        operation_id=str(op.id),
        new_status=OperationStatus.DELIVERED,
        actor=driver_of_carrier_x.user,
        driver_only=True,
    )

    op.refresh_from_db()
    assert op.status == OperationStatus.DELIVERED.value


# 29. Rota com transportadora de outro tenant deve ser rejeitada (perspectiva carrier)
@pytest.mark.django_db
def test_carrier_perspective_wrong_carrier_organization(org_carrier_x, customer_of_shipper_a, carrier_profile_y_under_shipper_a):
    # Route belongs to Org X, but carrier profile belongs to Org Y
    route = ContractedRoute(
        organization=org_carrier_x,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_y_under_shipper_a,
        name="Carrier perspective wrong org",
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
    )
    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "carrier" in exc.value.error_dict


    with pytest.raises(ValidationError) as exc:
        route.full_clean()
    assert "carrier" in exc.value.error_dict


# 31. Teste de fluxo normal de geração e materialização de rotas contratadas via serviço
@pytest.mark.django_db
def test_scheduler_service_success_flow(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")

    # 2026-08-24 is a Monday (MON) which is operating day for base_route
    target_date = datetime.date(2026, 8, 24)

    # Create stops on route template
    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )
    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=2,
        stop_type="DELIVERY",
        city="Rio de Janeiro",
        state="RJ",
    )

    from src.freights.application.route_services import GenerateDueContractedRouteOperationsService

    service = GenerateDueContractedRouteOperationsService(actor=manager_user_x)
    results = service.execute(target_date=target_date)

    assert results["routes_evaluated"] == 1
    assert results["occurrences_created"] == 1
    assert results["occurrences_processed"] == 1
    assert results["operations_created"] == 1
    assert results["operations_failed"] == 0

    # Assert occurrence and operation state
    occ = ContractedRouteOccurrence.objects.get(contracted_route=base_route_carrier_perspective, occurrence_date=target_date)
    assert occ.status == ContractedRouteOccurrenceStatus.MATERIALIZED.value
    assert occ.operation is not None
    assert occ.operation.source_type == OperationSource.CONTRACTED_ROUTE.value
    assert occ.operation.stops.count() == 2
    assert occ.operation.stops.get(sequence=1).city == "Sao Paulo"
    assert occ.operation.stops.get(sequence=2).city == "Rio de Janeiro"


# 32. Teste de idempotência (executar duas vezes não duplica nem altera nada)
@pytest.mark.django_db
def test_scheduler_service_idempotency(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    target_date = datetime.date(2026, 8, 24)

    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )

    from src.freights.application.route_services import GenerateDueContractedRouteOperationsService

    service = GenerateDueContractedRouteOperationsService(actor=manager_user_x)

    # Execução 1
    res1 = service.execute(target_date=target_date)
    assert res1["operations_created"] == 1

    # Execução 2
    res2 = service.execute(target_date=target_date)
    assert res2["operations_created"] == 0
    assert res2["already_existing"] == 0

    # Garantir que há exatamente uma ocorrência e uma operação no banco
    assert ContractedRouteOccurrence.objects.filter(contracted_route=base_route_carrier_perspective, occurrence_date=target_date).count() == 1
    assert FreightOperation.objects.filter(source_type=OperationSource.CONTRACTED_ROUTE.value).count() == 1


# 33. Teste de concorrência (dois threads disparando o scheduler ao mesmo tempo)
@pytest.mark.django_db(transaction=True)
def test_scheduler_service_concurrency(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    target_date = datetime.date(2026, 8, 24)

    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )

    from src.freights.application.route_services import GenerateDueContractedRouteOperationsService

    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            service = GenerateDueContractedRouteOperationsService(actor=manager_user_x)
            service.execute(target_date=target_date)
        except Exception as exc:
            errors.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, f"Erro inesperado: {errors}"

    # Deve haver exatamente uma ocorrência e uma operação
    assert ContractedRouteOccurrence.objects.filter(contracted_route=base_route_carrier_perspective, occurrence_date=target_date).count() == 1
    assert FreightOperation.objects.filter(source_type=OperationSource.CONTRACTED_ROUTE.value).count() == 1


# 34. Teste de restrição (rota inativa, weekday incorreto, vigência)
@pytest.mark.django_db
def test_scheduler_service_restrictions(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")

    from src.freights.application.route_services import GenerateDueContractedRouteOperationsService
    service = GenerateDueContractedRouteOperationsService(actor=manager_user_x)

    # Caso A: Rota Inativa
    base_route_carrier_perspective.status = ContractedRouteStatus.PAUSED.value
    base_route_carrier_perspective.save()
    res_inactive = service.execute(target_date=datetime.date(2026, 8, 24))
    assert res_inactive["routes_evaluated"] == 0
    assert res_inactive["occurrences_created"] == 0

    # Caso B: Fora da vigência
    base_route_carrier_perspective.status = ContractedRouteStatus.ACTIVE.value
    base_route_carrier_perspective.save()
    res_outside_vigencia = service.execute(target_date=datetime.date(2026, 9, 1)) # fora da vigência (fim em 31/08)
    assert res_outside_vigencia["routes_evaluated"] == 0

    # Caso C: Dia de semana incorreto
    # 2026-08-25 é terça-feira (TUE), mas a rota é MON, WED, FRI
    res_wrong_weekday = service.execute(target_date=datetime.date(2026, 8, 25))
    assert res_wrong_weekday["routes_evaluated"] == 0


# 35. Teste de robustez a falhas (um erro não impede os outros)
@pytest.mark.django_db
def test_scheduler_service_resilience(rbac_ready, base_route_carrier_perspective, org_carrier_x, customer_of_shipper_a, carrier_profile_x_own, manager_user_x, driver_of_carrier_y):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    target_date = datetime.date(2026, 8, 24)

    # Rota 1 (válida)
    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )

    # Rota 2 (inválida porque forçaremos um ValidationError ao atualizar o driver para outro tenant)
    route2 = ContractedRoute.objects.create(
        organization=org_carrier_x,
        customer=customer_of_shipper_a,
        carrier=carrier_profile_x_own,
        name="Rota Com Erro Validacao",
        status=ContractedRouteStatus.ACTIVE.value,
        valid_from=datetime.date(2026, 8, 1),
        valid_until=datetime.date(2026, 8, 31),
        load_type="FTL",
    )
    ContractedRouteWeekday.objects.create(route=route2, day=RouteWeekday.MON.value)

    # Criamos a ocorrência da rota 2 manualmente como planejada/válida
    occ2 = create_contracted_route_occurrence(
        route_id=str(route2.id),
        occurrence_date=target_date,
        actor=manager_user_x
    )

    # Agora atualizamos a ocorrência da rota 2 diretamente via banco com motorista de outro tenant (forçando erro)
    ContractedRouteOccurrence.objects.filter(id=occ2.id).update(driver_id=driver_of_carrier_y.id)

    from src.freights.application.route_services import GenerateDueContractedRouteOperationsService

    service = GenerateDueContractedRouteOperationsService(actor=manager_user_x)
    results = service.execute(target_date=target_date)

    assert results["routes_evaluated"] == 2
    assert results["operations_created"] == 1
    assert results["operations_failed"] == 1


# 36. Teste de execução do management command
@pytest.mark.django_db
def test_management_command_execution(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")

    # MON 2026-08-24
    target_date_str = "2026-08-24"
    target_date = datetime.date(2026, 8, 24)

    ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )

    # Criamos a ocorrência planejada no banco para que ela seja processada na simulação (dry-run)
    create_contracted_route_occurrence(
        route_id=str(base_route_carrier_perspective.id),
        occurrence_date=target_date,
        actor=manager_user_x
    )

    out = StringIO()
    err = StringIO()

    # Dry run test
    call_command(
        "process_contracted_routes",
        "--date", target_date_str,
        "--dry-run",
        stdout=out,
        stderr=err
    )

    assert "Runner do scheduler executado com sucesso!" in out.getvalue()
    assert "Operações de frete materializadas: 1" in out.getvalue()
    assert FreightOperation.objects.filter(source_type=OperationSource.CONTRACTED_ROUTE.value).count() == 0

    # Real run test
    out = StringIO()
    call_command(
        "process_contracted_routes",
        "--date", target_date_str,
        stdout=out,
        stderr=err
    )

    assert "Runner do scheduler executado com sucesso!" in out.getvalue()
    assert "Operações de frete materializadas: 1" in out.getvalue()
    assert FreightOperation.objects.filter(source_type=OperationSource.CONTRACTED_ROUTE.value).count() == 1


# 37. Teste de snapshot (alterar a rota contratada após a criação da operação não modifica a operação)
@pytest.mark.django_db
def test_scheduler_service_snapshot_isolation(rbac_ready, base_route_carrier_perspective, org_carrier_x, manager_user_x):
    grant_permission_to_user(manager_user_x, base_route_carrier_perspective.organization, "OPERATIONS_MANAGER")
    target_date = datetime.date(2026, 8, 24)

    stop = ContractedRouteStop.objects.create(
        organization=org_carrier_x,
        contracted_route=base_route_carrier_perspective,
        sequence=1,
        stop_type="PICKUP",
        city="Sao Paulo",
        state="SP",
    )

    from src.freights.application.route_services import GenerateDueContractedRouteOperationsService
    service = GenerateDueContractedRouteOperationsService(actor=manager_user_x)

    # Materializa a primeira vez
    service.execute(target_date=target_date)

    # Modificar o stop original
    stop.city = "Campinas"
    stop.save()

    # A operação gerada deve continuar com "Sao Paulo"
    op = FreightOperation.objects.get(source_type=OperationSource.CONTRACTED_ROUTE.value)
    op_stop = op.stops.get(sequence=1)
    assert op_stop.city == "Sao Paulo"
