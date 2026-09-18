# tests/test_operation_execution_hardened.py
"""Production-grade tests for the FreightOperation execution layer.

Validates:
1. Operational status transitions, validation, and state machine transitions
2. TrackingSession start, end, location point ingestion, and idempotency
3. Incident reporting and status preservation
4. POD recording, idempotency, concurrent safety, and automatic session closure
5. Complete End-to-End operational lifecycle flow
6. Multithreaded concurrency tests for status changes, tracking session creation, and POD creation
7. RBAC permissions of the DRIVER role vs administrative roles
8. Deduplication checks: retry by client_event_id and sequence, non-deduplication of same timestamp
9. POD idempotency matching vs conflicting inputs
"""

import pytest
import threading
from io import StringIO
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command
from django.utils import timezone

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.infrastructure.django.models import CarrierProfile, CarrierDriverLink
from src.customers.infrastructure.django.models import Customer
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.operation_services import (
    change_operation_status,
    report_operation_incident,
    cancel_operation,
    record_proof_of_delivery,
)
from src.freights.application.tracking_services import (
    start_tracking_session,
    record_location_point,
    end_tracking_session,
)
from src.freights.domain.enums import (
    OperationStatus,
    OperationEventType,
    TrackingSessionStatus,
)
from src.freights.domain.matching_enums import FreightOfferSelectionStatus
from src.freights.infrastructure.django.models import (
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    FreightOperationEvent,
    FreightQuote,
    FreightRequest,
    ProofOfDelivery,
    TrackingSession,
    LocationPoint,
)
from src.identity.domain.enums import PermissionCode
from src.shared.interfaces.backoffice.authorization import user_has_backoffice_permission
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.vehicles.infrastructure.django.models import Vehicle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def org_shipper(db):
    return Organization.objects.create(name="ShipperOrg", type=OrganizationType.CUSTOMER)


@pytest.fixture
def org_carrier_a(db):
    return Organization.objects.create(name="CarrierOrgA", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def org_carrier_b(db):
    return Organization.objects.create(name="CarrierOrgB", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def user_driver_a(db, django_user_model, org_carrier_a):
    u = django_user_model.objects.create_user(username="driver_a", password="password")
    Membership.objects.create(user=u, organization=org_carrier_a, status="ACTIVE")
    return u


@pytest.fixture
def user_driver_b(db, django_user_model, org_carrier_b):
    u = django_user_model.objects.create_user(username="driver_b", password="password")
    Membership.objects.create(user=u, organization=org_carrier_b, status="ACTIVE")
    return u


@pytest.fixture
def user_admin(db, django_user_model, org_carrier_a):
    u = django_user_model.objects.create_user(username="admin_carrier", password="password", is_superuser=True)
    Membership.objects.create(user=u, organization=org_carrier_a, status="ACTIVE")
    return u


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
def driver_a(db, org_carrier_a, user_driver_a):
    d = Driver.objects.create(organization=org_carrier_a, full_name="Driver A", status="ACTIVE")
    user_driver_a.driver_profiles.add(d)
    return d


@pytest.fixture
def driver_b(db, org_carrier_b, user_driver_b):
    d = Driver.objects.create(organization=org_carrier_b, full_name="Driver B", status="ACTIVE")
    user_driver_b.driver_profiles.add(d)
    return d


@pytest.fixture
def vehicle_a(db, org_carrier_a):
    return Vehicle.objects.create(organization=org_carrier_a, plate="CAR-1111", vehicle_type="CAR", status="ACTIVE")


@pytest.fixture
def customer(db, org_shipper):
    return Customer.objects.create(
        organization=org_shipper,
        legal_name="Shipper Customer",
        document_number="12345678901",
        email="shipper@example.com",
    )


@pytest.fixture
def operation_assigned(db, org_shipper, org_carrier_a, user_admin, customer, carrier_profile_a, driver_a, vehicle_a):
    # Setup the pipeline request -> quote -> offer -> selection -> operation
    request = FreightRequest.objects.create(
        organization=org_shipper,
        customer=customer,
        created_by=user_admin,
        reference_code="REQ-OP",
    )
    quote = FreightQuote.objects.create(
        organization=org_shipper,
        freight_request=request,
        created_by=user_admin,
        reference_code="QT-OP",
    )
    offer = FreightOffer.objects.create(
        organization=org_shipper,
        freight_request=request,
        freight_quote=quote,
        created_by=user_admin,
        reference_code="OFR-OP",
    )
    interest = FreightOfferInterest.objects.create(
        organization=org_carrier_a,
        offer=offer,
        carrier=carrier_profile_a,
        driver=driver_a,
        vehicle=vehicle_a,
        status="CONFIRMED",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest,
        organization=org_shipper,
        offer=offer,
        status=FreightOfferSelectionStatus.CONFIRMED.value,
        selected_by=user_admin,
        selected_at=timezone.now(),
    )
    operation = FreightOperation.objects.create(
        organization=org_shipper,
        selection=selection,
        carrier=carrier_profile_a,
        driver=driver_a,
        vehicle=vehicle_a,
        status=OperationStatus.ASSIGNED.value,
        assigned_at=timezone.now(),
    )
    # Grant active memberships roles to allow action views/services
    CarrierDriverLink.objects.get_or_create(carrier=carrier_profile_a, driver=driver_a, active=True)
    return operation


def grant_permission_to_user(user, org, role_code):
    role = Role.objects.get(code=role_code)
    membership, _ = Membership.objects.get_or_create(user=user, organization=org, defaults={"status": "ACTIVE"})
    MembershipRole.objects.get_or_create(membership=membership, role=role)


# ---------------------------------------------------------------------------
# 1. Operational status transitions, validation, and state machine
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_advance_status_valid(user_driver_a, operation_assigned, rbac_ready):
    """Driver transitions ASSIGNED -> DRIVER_EN_ROUTE_TO_PICKUP."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    op = change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
        actor=user_driver_a,
        driver_only=True
    )
    assert op.status == OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP.value
    assert op.events.filter(event_type=OperationEventType.STATUS_CHANGED.value).exists()


@pytest.mark.django_db
def test_advance_status_invalid_jump(user_driver_a, operation_assigned, rbac_ready):
    """Skipping status (ASSIGNED -> DELIVERED) is rejected."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    with pytest.raises(ValidationError) as exc:
        change_operation_status(
            operation_id=str(operation_assigned.id),
            new_status=OperationStatus.DELIVERED,
            actor=user_driver_a,
            driver_only=True
        )
    assert "Transição de status não permitida" in str(exc.value)


@pytest.mark.django_db
def test_advance_status_incorrect_driver(user_driver_b, operation_assigned, rbac_ready):
    """A driver who is not assigned to the operation cannot view or modify it."""
    grant_permission_to_user(user_driver_b, operation_assigned.organization, "DRIVER")

    with pytest.raises(ValidationError) as exc:
        change_operation_status(
            operation_id=str(operation_assigned.id),
            new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
            actor=user_driver_b,
            driver_only=True
        )
    assert "Operação não encontrada" in str(exc.value)


@pytest.mark.django_db
def test_advance_status_idempotent(user_driver_a, operation_assigned, rbac_ready):
    """Calling with same status returns it idempotently."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    op1 = change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
        actor=user_driver_a,
        driver_only=True
    )
    op2 = change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
        actor=user_driver_a,
        driver_only=True
    )
    assert op1.id == op2.id
    assert op2.status == OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP.value


# ---------------------------------------------------------------------------
# 2. TrackingSession start, end, location points ingestion, and idempotency
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_tracking_lifecycle(user_driver_a, operation_assigned, rbac_ready):
    """Start tracking -> Record point -> Deduplicate point -> End tracking."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    # 1. Start tracking session
    session = start_tracking_session(
        actor=user_driver_a,
        operation_id=str(operation_assigned.id),
        source="mobile"
    )
    assert session.status == TrackingSessionStatus.ACTIVE.value
    assert session.operation_id == operation_assigned.id

    # 2. Ingest a valid point
    t1 = timezone.now()
    pt = record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0,
        recorded_at=t1,
        client_event_id="point-111"
    )
    assert float(pt.latitude) == -23.550520
    assert pt.client_event_id == "point-111"

    # 3. Deduplicate / Retry point (same client_event_id)
    pt_dup = record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0,
        recorded_at=t1,
        client_event_id="point-111"
    )
    assert pt_dup.id == pt.id
    assert LocationPoint.objects.filter(tracking_session=session).count() == 1

    # 4. Deduplicate point (same sequence)
    pt_dup_seq = record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0,
        recorded_at=timezone.now(),
        sequence=1
    )
    pt_dup_seq_2 = record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0,
        recorded_at=timezone.now(),
        sequence=1
    )
    assert pt_dup_seq.id == pt_dup_seq_2.id

    # 5. Two points at same timestamp with different client_event_id or sequences are NOT discarded
    pt_time_1 = record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0,
        recorded_at=t1,
        client_event_id="point-time-1"
    )
    pt_time_2 = record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0,
        recorded_at=t1,
        client_event_id="point-time-2"
    )
    assert pt_time_1.id != pt_time_2.id

    # 6. Ingest invalid coordinates
    with pytest.raises(ValidationError):
        record_location_point(
            actor=user_driver_a,
            tracking_session_id=str(session.id),
            latitude=95.0,
            longitude=-46.633308,
            accuracy_m=5.0
        )

    # 7. End session
    session_ended = end_tracking_session(
        actor=user_driver_a,
        tracking_session_id=str(session.id)
    )
    assert session_ended.status == TrackingSessionStatus.ENDED.value

    # 8. Ingestion on ended session is rejected
    with pytest.raises(ValidationError) as exc:
        record_location_point(
            actor=user_driver_a,
            tracking_session_id=str(session.id),
            latitude=-23.550520,
            longitude=-46.633308,
            accuracy_m=5.0,
            recorded_at=timezone.now()
        )
    assert "Não é possível registrar pontos" in str(exc.value)


@pytest.mark.django_db
def test_tracking_start_no_permission(user_driver_a, operation_assigned, rbac_ready):
    """A driver without backoffice roles (e.g. not even a Membership Role) is rejected."""
    # User user_driver_a is a member but has no MembershipRole linking it to a Role.
    with pytest.raises(PermissionDenied):
        start_tracking_session(
            actor=user_driver_a,
            operation_id=str(operation_assigned.id),
            source="mobile"
        )


# ---------------------------------------------------------------------------
# 3. Incident reporting and status preservation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_report_incident(user_driver_a, operation_assigned, rbac_ready):
    """Driver reports incident, main status of the operation remains ASSIGNED."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    event = report_operation_incident(
        operation_id=str(operation_assigned.id),
        description="Furo no pneu na rodovia.",
        actor=user_driver_a,
        driver_only=True
    )
    assert event.event_type == OperationEventType.INCIDENT_REPORTED.value
    assert event.metadata["description"] == "Furo no pneu na rodovia."

    operation_assigned.refresh_from_db()
    assert operation_assigned.status == OperationStatus.ASSIGNED.value


# ---------------------------------------------------------------------------
# 4. POD recording, idempotency, concurrent safety, and automatic session closure
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pod_recording_and_terminal_transitions(user_driver_a, operation_assigned, rbac_ready):
    """POD can only be recorded in UNLOADING state, triggers automatic tracking session closure upon delivery."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    # 1. Start tracking session
    session = start_tracking_session(
        actor=user_driver_a,
        operation_id=str(operation_assigned.id),
        source="mobile"
    )
    assert session.status == TrackingSessionStatus.ACTIVE.value

    # 2. Advance to UNLOADING
    operation_assigned.status = OperationStatus.UNLOADING.value
    operation_assigned.save()

    # 3. Record POD
    t_delivered = timezone.now()
    pod = record_proof_of_delivery(
        operation_id=str(operation_assigned.id),
        receiver_name="John Doe Receiver",
        delivered_at=t_delivered,
        actor=user_driver_a,
        driver_only=True
    )
    assert pod.receiver_name == "John Doe Receiver"
    assert pod.operation_id == operation_assigned.id

    # 4. Recording duplicate POD with identical payload returns the existing one idempotently
    pod_dup = record_proof_of_delivery(
        operation_id=str(operation_assigned.id),
        receiver_name="John Doe Receiver",
        delivered_at=t_delivered,
        actor=user_driver_a,
        driver_only=True
    )
    assert pod_dup.id == pod.id

    # 5. Recording duplicate POD with DIFFERENT payload triggers ValidationError
    with pytest.raises(ValidationError) as exc:
        record_proof_of_delivery(
            operation_id=str(operation_assigned.id),
            receiver_name="Carlos Conflict Receiver",
            delivered_at=t_delivered,
            actor=user_driver_a,
            driver_only=True
        )
    assert "dados diferentes" in str(exc.value)

    # 6. Transition to DELIVERED
    op_delivered = change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.DELIVERED,
        actor=user_driver_a,
        driver_only=True
    )
    assert op_delivered.status == OperationStatus.DELIVERED.value

    # 7. Verify active tracking sessions were automatically closed with reason
    session.refresh_from_db()
    assert session.status == TrackingSessionStatus.ENDED.value
    assert session.device_metadata["closure_reason"] == "operation_delivered"


# ---------------------------------------------------------------------------
# 5. Complete End-to-End Operational Lifecycle Flow
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_full_operational_lifecycle_e2e(user_driver_a, operation_assigned, rbac_ready):
    """Full operational pipeline: ASSIGNED -> DRIVER_EN_ROUTE_TO_PICKUP -> start tracking -> locations -> incident -> arrived -> loading -> in transit -> arrived delivery -> unloading -> POD -> DELIVERED -> tracking session closed."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    # ASSIGNED -> DRIVER_EN_ROUTE_TO_PICKUP
    change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
        actor=user_driver_a,
        driver_only=True
    )

    # Start tracking session
    session = start_tracking_session(
        actor=user_driver_a,
        operation_id=str(operation_assigned.id),
        source="mobile"
    )

    # Ingest a point
    record_location_point(
        actor=user_driver_a,
        tracking_session_id=str(session.id),
        latitude=-23.550520,
        longitude=-46.633308,
        accuracy_m=5.0
    )

    # Report incident
    report_operation_incident(
        operation_id=str(operation_assigned.id),
        description="Forte chuva atrasando percurso.",
        actor=user_driver_a,
        driver_only=True
    )

    # DRIVER_EN_ROUTE_TO_PICKUP -> ARRIVED_AT_PICKUP
    change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.ARRIVED_AT_PICKUP,
        actor=user_driver_a,
        driver_only=True
    )

    # ARRIVED_AT_PICKUP -> LOADING
    change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.LOADING,
        actor=user_driver_a,
        driver_only=True
    )

    # LOADING -> IN_TRANSIT
    change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.IN_TRANSIT,
        actor=user_driver_a,
        driver_only=True
    )

    # IN_TRANSIT -> ARRIVED_AT_DELIVERY
    change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.ARRIVED_AT_DELIVERY,
        actor=user_driver_a,
        driver_only=True
    )

    # ARRIVED_AT_DELIVERY -> UNLOADING
    change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.UNLOADING,
        actor=user_driver_a,
        driver_only=True
    )

    # Create POD
    record_proof_of_delivery(
        operation_id=str(operation_assigned.id),
        receiver_name="Alice Smith",
        delivered_at=timezone.now(),
        actor=user_driver_a,
        driver_only=True
    )

    # UNLOADING -> DELIVERED
    op_final = change_operation_status(
        operation_id=str(operation_assigned.id),
        new_status=OperationStatus.DELIVERED,
        actor=user_driver_a,
        driver_only=True
    )
    assert op_final.status == OperationStatus.DELIVERED.value

    # Verify session automatically ended
    session.refresh_from_db()
    assert session.status == TrackingSessionStatus.ENDED.value
    assert session.device_metadata["closure_reason"] == "operation_delivered"


# ---------------------------------------------------------------------------
# 6. Concurrency tests using real threads and connections
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_concurrent_status_advances(user_driver_a, operation_assigned, rbac_ready):
    """Two concurrent status updates return same final operation status without integrity issues."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            op = change_operation_status(
                operation_id=str(operation_assigned.id),
                new_status=OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
                actor=user_driver_a,
                driver_only=True
            )
            results.append(op.status)
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
    assert results[0] == results[1] == OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP.value


@pytest.mark.django_db(transaction=True)
def test_concurrent_start_tracking_sessions(user_driver_a, operation_assigned, rbac_ready):
    """Concurrent start tracking requests produce exactly 1 active tracking session."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            session = start_tracking_session(
                actor=user_driver_a,
                operation_id=str(operation_assigned.id),
                source="mobile"
            )
            results.append(session.id)
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
    assert TrackingSession.objects.filter(operation=operation_assigned, status="ACTIVE").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_proof_of_delivery_recording(user_driver_a, operation_assigned, rbac_ready):
    """Concurrent POD recording calls resolve to exactly 1 recorded POD."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    operation_assigned.status = OperationStatus.UNLOADING.value
    operation_assigned.save()

    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)
    t_delivered = timezone.now()

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            pod = record_proof_of_delivery(
                operation_id=str(operation_assigned.id),
                receiver_name="Jane Doe",
                delivered_at=t_delivered,
                actor=user_driver_a,
                driver_only=True
            )
            results.append(pod.id)
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
    assert ProofOfDelivery.objects.filter(operation=operation_assigned).count() == 1


# ---------------------------------------------------------------------------
# 7. DRIVER role permissions vs administrative roles
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_driver_role_permissions(user_driver_a, operation_assigned, rbac_ready):
    """DRIVER user has only operational permissions, no administrative ones."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    # Operational permissions allowed
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.FREIGHT_OPERATIONS_VIEW.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.FREIGHT_OPERATIONS_REPORT_INCIDENT.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.FREIGHT_OPERATIONS_RECORD_POD.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.TRACKING_VIEW.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.TRACKING_START.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.TRACKING_RECORD.value)
    assert user_has_backoffice_permission(user_driver_a, PermissionCode.TRACKING_END.value)

    # Admin permissions denied
    assert not user_has_backoffice_permission(user_driver_a, PermissionCode.DRIVERS_APPROVE.value)
    assert not user_has_backoffice_permission(user_driver_a, PermissionCode.ORGANIZATIONS_MANAGE.value)
    assert not user_has_backoffice_permission(user_driver_a, PermissionCode.USERS_CREATE.value)


# ---------------------------------------------------------------------------
# 8. Operation status terminal session closures
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cancel_operation_closes_active_tracking_sessions(user_driver_a, operation_assigned, rbac_ready):
    """Transitioning to CANCELLED terminates any active tracking session."""
    grant_permission_to_user(user_driver_a, operation_assigned.organization, "DRIVER")

    # Start tracking session
    session = start_tracking_session(
        actor=user_driver_a,
        operation_id=str(operation_assigned.id),
        source="mobile"
    )
    assert session.status == TrackingSessionStatus.ACTIVE.value

    # Cancel operation
    cancel_operation(
        operation_id=str(operation_assigned.id),
        reason="Veículo quebrado",
        actor=user_driver_a
    )

    # Verify session is ended
    session.refresh_from_db()
    assert session.status == TrackingSessionStatus.ENDED.value
    assert session.device_metadata["closure_reason"] == "operation_cancelled"
