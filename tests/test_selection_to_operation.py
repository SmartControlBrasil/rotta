# tests/test_selection_to_operation.py
"""Production-grade tests for the Selection → FreightOperation flow.

Validates:
- Normal creation from a confirmed selection
- Sequential idempotency (same operation returned)
- Concurrent creation safety (real DB + threads)
- Rejection of non-CONFIRMED selections (PENDING, DECLINED, CANCELLED, EXPIRED)
- Cross-tenant isolation
- Permission / authorization checks
- Driver / vehicle tenant compatibility
- Rollback on error (no partial state)
- Audit event creation (exactly once)
- Audit idempotency (no duplicate on repeat call)
"""

import pytest
import threading
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.infrastructure.django.models import CarrierProfile
from src.customers.infrastructure.django.models import Customer
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.operation_services import create_operation_from_selection
from src.freights.domain.enums import OperationStatus
from src.freights.domain.matching_enums import FreightOfferSelectionStatus
from src.freights.infrastructure.django.models import (
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    FreightOperationEvent,
    FreightQuote,
    FreightRequest,
)
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.infrastructure.django.models import Membership, Organization
from src.vehicles.infrastructure.django.models import Vehicle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="TestOrg")


@pytest.fixture
def org_other(db):
    return Organization.objects.create(name="OtherOrg")


@pytest.fixture
def user_super(db, django_user_model, org):
    u = django_user_model.objects.create_user(
        username="superuser", password="secret", is_superuser=True
    )
    Membership.objects.create(user=u, organization=org, status="ACTIVE")
    return u


@pytest.fixture
def user_regular(db, django_user_model, org):
    """A regular user with membership to org."""
    u = django_user_model.objects.create_user(username="regular", password="secret")
    Membership.objects.create(user=u, organization=org, status="ACTIVE")
    return u


@pytest.fixture
def user_other_org(db, django_user_model, org_other):
    """A regular user belonging only to org_other."""
    u = django_user_model.objects.create_user(username="otheruser", password="secret")
    Membership.objects.create(user=u, organization=org_other, status="ACTIVE")
    return u


@pytest.fixture
def user_no_membership(db, django_user_model):
    """A user with no memberships at all."""
    return django_user_model.objects.create_user(username="nomember", password="secret")


@pytest.fixture
def carrier(db, org):
    return CarrierProfile.objects.create(
        organization=org,
        tenant=org,
        trade_name="ActiveCarrier",
        status="ACTIVE",
    )


@pytest.fixture
def carrier_prospect(db, org):
    return CarrierProfile.objects.create(
        organization=org,
        tenant=org,
        trade_name="ProspectCarrier",
        status="PROSPECT",
    )


@pytest.fixture
def driver(db, org):
    return Driver.objects.create(organization=org, full_name="Test Driver")


@pytest.fixture
def driver_other_org(db, org_other):
    return Driver.objects.create(organization=org_other, full_name="Other Org Driver")


@pytest.fixture
def vehicle(db, org):
    return Vehicle.objects.create(organization=org, plate="ABC1234", vehicle_type="CAR")


@pytest.fixture
def vehicle_other_org(db, org_other):
    return Vehicle.objects.create(organization=org_other, plate="XYZ9999", vehicle_type="CAR")


@pytest.fixture
def customer(db, org):
    return Customer.objects.create(
        organization=org,
        legal_name="Test Customer",
        document_number="12345678901",
        email="customer@example.com",
    )


@pytest.fixture
def freight_request(db, org, user_super, customer):
    return FreightRequest.objects.create(
        organization=org,
        customer=customer,
        created_by=user_super,
        reference_code="REQ-TEST",
    )


@pytest.fixture
def freight_quote(db, org, freight_request, user_super):
    return FreightQuote.objects.create(
        organization=org,
        freight_request=freight_request,
        created_by=user_super,
        reference_code="QT-TEST",
        status="DRAFT",
    )


@pytest.fixture
def freight_offer(db, org, freight_request, freight_quote, user_super):
    return FreightOffer.objects.create(
        organization=org,
        freight_request=freight_request,
        freight_quote=freight_quote,
        created_by=user_super,
        reference_code="OFR-TEST",
        status="DRAFT",
    )


def _make_interest(org, offer, carrier, driver, vehicle, status="ACTIVE"):
    return FreightOfferInterest.objects.create(
        organization=org,
        offer=offer,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status=status,
        expressed_at=timezone.now(),
    )


def _make_selection(org, offer, interest, user, status):
    return FreightOfferSelection.objects.create(
        organization=org,
        offer=offer,
        interest=interest,
        selected_by=user,
        selected_at=timezone.now(),
        status=status,
    )


@pytest.fixture
def confirmed_selection(
    org, freight_offer, carrier, driver, vehicle, user_super
):
    """A fully valid CONFIRMED selection ready to produce an operation."""
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    return _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )


# ---------------------------------------------------------------------------
# Case 1 — normal creation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_operation_normal(user_super, confirmed_selection, org):
    """A confirmed selection with valid carrier/driver/vehicle creates one FreightOperation."""
    operation = create_operation_from_selection(
        selection_id=confirmed_selection.id,
        actor=user_super,
    )

    assert isinstance(operation, FreightOperation)
    assert operation.selection_id == confirmed_selection.id
    assert operation.organization_id == org.id
    assert operation.status == OperationStatus.ASSIGNED.value
    assert operation.carrier is not None
    assert operation.driver is not None
    assert operation.vehicle is not None
    assert FreightOperation.objects.filter(selection=confirmed_selection).count() == 1

    event = FreightOperationEvent.objects.get(
        operation=operation, event_type="OPERATION_CREATED"
    )
    assert event.new_status == OperationStatus.ASSIGNED.value


# ---------------------------------------------------------------------------
# Case 2 — idempotent sequential calls
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_idempotent_sequential(user_super, confirmed_selection):
    """Calling the service twice returns the same operation. COUNT = 1."""
    op1 = create_operation_from_selection(
        selection_id=confirmed_selection.id, actor=user_super
    )
    op2 = create_operation_from_selection(
        selection_id=confirmed_selection.id, actor=user_super
    )

    assert op1.id == op2.id
    assert FreightOperation.objects.filter(selection=confirmed_selection).count() == 1


# ---------------------------------------------------------------------------
# Case 3 — concurrent creation (real DB + threads)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_concurrent_creation(
    org, freight_offer, carrier, driver, vehicle, user_super
):
    """Two threads creating an operation for the same selection produce exactly 1 row."""
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    results = []
    errors = []
    barrier = threading.Barrier(2, timeout=10)

    def worker():
        from django.db import connection as conn
        try:
            barrier.wait()
            op = create_operation_from_selection(
                selection_id=selection.id, actor=user_super
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
    assert results[0] == results[1], "Both threads should return the same operation"
    assert FreightOperation.objects.filter(selection=selection).count() == 1


# ---------------------------------------------------------------------------
# Case 4 — selection PENDING rejected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_reject_pending_selection(
    org, freight_offer, carrier, driver, vehicle, user_super
):
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.PENDING_CONFIRMATION.value,
    )

    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(selection_id=selection.id, actor=user_super)
    assert "confirmada" in str(exc.value)
    assert FreightOperation.objects.filter(selection=selection).count() == 0


# ---------------------------------------------------------------------------
# Case 5 — selection DECLINED / CANCELLED rejected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_reject_declined_selection(
    org, freight_offer, carrier, driver, vehicle, user_super
):
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.DECLINED.value,
    )

    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(selection_id=selection.id, actor=user_super)
    assert "confirmada" in str(exc.value)


@pytest.mark.django_db
def test_reject_cancelled_selection(
    org, freight_offer, carrier, driver, vehicle, user_super
):
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CANCELLED.value,
    )

    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(selection_id=selection.id, actor=user_super)
    assert "confirmada" in str(exc.value)


@pytest.mark.django_db
def test_reject_expired_selection(
    org, freight_offer, carrier, driver, vehicle, user_super
):
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.EXPIRED.value,
    )

    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(selection_id=selection.id, actor=user_super)
    assert "confirmada" in str(exc.value)


# ---------------------------------------------------------------------------
# Case 6 — cross-tenant rejected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cross_tenant_rejected(user_other_org, confirmed_selection):
    """An actor from a different organization cannot create the operation."""
    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(
            selection_id=confirmed_selection.id, actor=user_other_org
        )
    assert "Acesso negado" in str(exc.value)
    assert FreightOperation.objects.filter(selection=confirmed_selection).count() == 0


# ---------------------------------------------------------------------------
# Case 7 — no membership rejected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_no_membership_rejected(user_no_membership, confirmed_selection):
    """An actor with no memberships cannot create the operation."""
    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(
            selection_id=confirmed_selection.id, actor=user_no_membership
        )
    assert "Acesso negado" in str(exc.value)


# ---------------------------------------------------------------------------
# Case 8 — driver from different org rejected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_driver_different_org_rejected(
    org, org_other, freight_offer, carrier, driver_other_org, vehicle, user_super
):
    """A driver from a different org than the carrier's tenant should be rejected."""
    interest = _make_interest(
        org, freight_offer, carrier, driver_other_org, vehicle
    )
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(selection_id=selection.id, actor=user_super)
    assert "tenant diferente" in str(exc.value)


# ---------------------------------------------------------------------------
# Case 9 — vehicle from different org rejected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_vehicle_different_org_rejected(
    org, org_other, freight_offer, carrier, driver, vehicle_other_org, user_super
):
    """A vehicle from a different org than the carrier's tenant should be rejected."""
    interest = _make_interest(
        org, freight_offer, carrier, driver, vehicle_other_org
    )
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(selection_id=selection.id, actor=user_super)
    assert "tenant diferente" in str(exc.value)


# ---------------------------------------------------------------------------
# Case 10 — existing operation returned
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_existing_operation_returned(user_super, confirmed_selection):
    """If an operation already exists, the same one is returned."""
    op1 = create_operation_from_selection(
        selection_id=confirmed_selection.id, actor=user_super
    )
    op2 = create_operation_from_selection(
        selection_id=confirmed_selection.id, actor=user_super
    )
    op3 = create_operation_from_selection(
        selection_id=confirmed_selection.id, actor=user_super
    )

    assert op1.id == op2.id == op3.id
    assert FreightOperation.objects.filter(selection=confirmed_selection).count() == 1


# ---------------------------------------------------------------------------
# Case 11 — rollback on error (no partial state)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_rollback_on_carrier_inactive(
    org, freight_offer, carrier_prospect, driver, vehicle, user_super
):
    """If carrier is not ACTIVE, no operation or events are created."""
    interest = _make_interest(
        org, freight_offer, carrier_prospect, driver, vehicle
    )
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    with pytest.raises(ValidationError):
        create_operation_from_selection(selection_id=selection.id, actor=user_super)

    assert FreightOperation.objects.filter(selection=selection).count() == 0
    assert FreightOperationEvent.objects.count() == 0


# ---------------------------------------------------------------------------
# Case 12 — audit event on creation
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_audit_event_on_creation(user_super, org, freight_offer, carrier, driver, vehicle):
    """Actual creation produces exactly one audit log entry."""
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    create_operation_from_selection(
        selection_id=selection.id, actor=user_super
    )

    # record_audit_event uses on_commit, so with transaction=True it fires immediately
    audit_entries = AuditLog.objects.filter(action="freight_operation_created")
    assert audit_entries.count() == 1
    entry = audit_entries.first()
    assert str(selection.id) in str(entry.after)


# ---------------------------------------------------------------------------
# Case 13 — idempotent audit (no duplicate on repeat)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_audit_idempotent(user_super, org, freight_offer, carrier, driver, vehicle):
    """A repeat call does NOT produce a second 'freight_operation_created' audit entry."""
    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, user_super,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    create_operation_from_selection(selection_id=selection.id, actor=user_super)
    create_operation_from_selection(selection_id=selection.id, actor=user_super)

    audit_entries = AuditLog.objects.filter(action="freight_operation_created")
    assert audit_entries.count() == 1


# ---------------------------------------------------------------------------
# Case 14 — superuser bypasses tenant check
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_superuser_bypasses_tenant_check(
    org, org_other, freight_offer, carrier, driver, vehicle, django_user_model
):
    """A superuser without membership to the org can still create the operation."""
    superuser = django_user_model.objects.create_user(
        username="super_external", password="secret", is_superuser=True
    )
    # Superuser has NO membership to org

    interest = _make_interest(org, freight_offer, carrier, driver, vehicle)
    selection = _make_selection(
        org, freight_offer, interest, superuser,
        FreightOfferSelectionStatus.CONFIRMED.value,
    )

    operation = create_operation_from_selection(
        selection_id=selection.id, actor=superuser
    )
    assert operation.selection_id == selection.id


# ---------------------------------------------------------------------------
# Case 15 — selection not found
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_selection_not_found(user_super):
    import uuid
    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(
            selection_id=uuid.uuid4(), actor=user_super
        )
    assert "não encontrada" in str(exc.value)
