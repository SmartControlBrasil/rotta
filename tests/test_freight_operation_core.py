# tests/test_freight_operation_core.py
"""Tests for the FreightOperation core services.
Ensures that a confirmed FreightOfferSelection creates a FreightOperation
exactly once, validates carrier status, and respects idempotency.
"""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from src.organizations.infrastructure.django.models import Organization
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer
from src.customers.domain.enums import CustomerStatus
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    FreightOperationEvent,
)
from src.freights.application.operation_services import (
    create_operation_from_selection,
)

@pytest.fixture
def organization(db):
    return Organization.objects.create(name="TestOrg")

@pytest.fixture
def user(db, organization):
    # Create a simple user associated with the organization
    from django.contrib.auth import get_user_model
    User = get_user_model()
    # Create a simple user without direct organization association.
    user = User.objects.create_user(
        username="testuser",
        password="secret",
        is_staff=True,
        is_superuser=True,
    )
    # Associate the user with the organization via Membership.
    from src.organizations.infrastructure.django.models import Membership
    Membership.objects.create(user=user, organization=organization)
    return user

@pytest.fixture

def carrier_active(db, organization):
    return CarrierProfile.objects.create(
        organization=organization,
        tenant=organization,
        trade_name="ActiveCarrier",
        status="ACTIVE",
    )

@pytest.fixture

def carrier_prospect(db, organization):
    return CarrierProfile.objects.create(
        organization=organization,
        tenant=organization,
        trade_name="ProspectCarrier",
        status="PROSPECT",
    )


@pytest.fixture
def vehicle(db, organization):
    from src.vehicles.infrastructure.django.models import Vehicle
    return Vehicle.objects.create(
        organization=organization,
        plate="ABC1234",
        vehicle_type="CAR",
    )
@pytest.fixture
def driver(db, organization):
    from src.drivers.infrastructure.django.models import Driver
    return Driver.objects.create(organization=organization, full_name="Test Driver")





@pytest.fixture
def customer(db, organization):
    return Customer.objects.create(
        organization=organization,
        legal_name="Test Customer",
        document_number="12345678901",
        email="customer@example.com",
    )


@pytest.fixture
def freight_request(db, organization, user, customer):
    return FreightRequest.objects.create(
        organization=organization,
        customer=customer,
        created_by=user,
        reference_code="REQ001",
    )

@pytest.fixture
def freight_quote(db, organization, freight_request, user):
    return FreightQuote.objects.create(
        organization=organization,
        freight_request=freight_request,
        created_by=user,
        reference_code="QT001",
        status="DRAFT",
    )

@pytest.fixture
def freight_offer(db, organization, freight_request, freight_quote, user):
    return FreightOffer.objects.create(
        organization=organization,
        freight_request=freight_request,
        freight_quote=freight_quote,
        created_by=user,
        reference_code="OFR001",
        status="DRAFT",
    )

@pytest.fixture
def interest_active(db, freight_offer, carrier_active, driver, vehicle, organization):
    return FreightOfferInterest.objects.create(
        organization=organization,
        offer=freight_offer,
        carrier=carrier_active,
        driver=driver,
        vehicle=vehicle,
        status="CONFIRMED",
        expressed_at=timezone.now(),
    )

@pytest.fixture
def selection_confirmed(db, interest_active, organization, user):
    return FreightOfferSelection.objects.create(
        interest=interest_active,
        organization=organization,
        offer=interest_active.offer,
        status="CONFIRMED",
        selected_by=user,
        selected_at=timezone.now(),
    )

@pytest.mark.django_db
def test_create_operation_success(user, selection_confirmed, organization):
    """A confirmed selection should create a FreightOperation exactly once."""
    operation = create_operation_from_selection(
        selection_id=selection_confirmed.id,
        actor=user,
    )

    assert isinstance(operation, FreightOperation)
    assert operation.selection_id == selection_confirmed.id
    assert operation.organization_id == organization.id
    from src.freights.domain.enums import OperationStatus
    assert operation.status == OperationStatus.ASSIGNED.value

    event = FreightOperationEvent.objects.get(operation=operation)
    assert event.event_type == "OPERATION_CREATED"

@pytest.mark.django_db
def test_create_operation_idempotent(user, selection_confirmed):
    """Calling the service twice should return the same operation and create a second event only if a client_event_id is supplied."""
    op1 = create_operation_from_selection(
        selection_id=selection_confirmed.id,
        actor=user,
        client_event_id="evt-123",
    )
    op2 = create_operation_from_selection(
        selection_id=selection_confirmed.id,
        actor=user,
    )
    assert op1.id == op2.id
    assert FreightOperationEvent.objects.filter(operation=op1).count() == 1

    op3 = create_operation_from_selection(
        selection_id=selection_confirmed.id,
        actor=user,
        client_event_id="evt-456",
    )
    assert op3.id == op1.id
    assert FreightOperationEvent.objects.filter(operation=op1).count() == 2

@pytest.mark.django_db
def test_create_operation_with_prospect_carrier(user, organization, freight_offer, driver, vehicle, carrier_prospect):
    """A selection linked to a PROSPECT carrier must raise a ValidationError."""
    interest = FreightOfferInterest.objects.create(
        organization=organization,
        offer=freight_offer,
        carrier=carrier_prospect,
        driver=driver,
        vehicle=vehicle,
        status="CONFIRMED",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest,
        organization=organization,
        offer=freight_offer,
        status="CONFIRMED",
        selected_by=user,
        selected_at=timezone.now(),
    )
    with pytest.raises(ValidationError) as exc:
        create_operation_from_selection(
            selection_id=selection.id,
            actor=user,
        )
    assert "Transportadora deve estar com status ACTIVE" in str(exc.value)
