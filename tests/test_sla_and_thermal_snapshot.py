import datetime
from decimal import Decimal
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model

from src.organizations.infrastructure.django.models import Organization
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer
from src.freights.domain.enums import (
    OperationStatus,
    FreightStopType,
    OperationSource,
)
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestStop,
    FreightRequestCargo,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    FreightOperationStop,
    ContractedRoute,
    ContractedRouteStop,
    ContractedRouteOccurrence,
    ThermalReading,
    ThermalExcursion,
)
from src.freights.application.operation_services import (
    create_operation_from_selection,
    record_thermal_reading,
)
from src.freights.application.route_services import (
    materialize_contracted_route_occurrence,
)
from src.freights.application.sla_service import SLAService, SLAState

@pytest.fixture
def setup_data(db):
    User = get_user_model()
    org = Organization.objects.create(name="LogisticsOrg")
    user = User.objects.create_user(username="test_sla_user", password="password", is_superuser=True)

    carrier = CarrierProfile.objects.create(
        organization=org, tenant=org, trade_name="Test Carrier", status="ACTIVE"
    )
    driver = Driver.objects.create(organization=org, full_name="Test Driver")
    vehicle = Vehicle.objects.create(organization=org, plate="ABC1234", vehicle_type="TRUCK")

    customer = Customer.objects.create(
        organization=org,
        legal_name="Test Customer",
        document_number="12345678901",
        email="c@customer.com",
    )

    return {
        "org": org,
        "user": user,
        "carrier": carrier,
        "driver": driver,
        "vehicle": vehicle,
        "customer": customer,
    }

@pytest.mark.django_db
def test_marketplace_operation_sla_and_thermal(setup_data):
    org = setup_data["org"]
    user = setup_data["user"]
    carrier = setup_data["carrier"]
    driver = setup_data["driver"]
    vehicle = setup_data["vehicle"]
    customer = setup_data["customer"]

    # 1. Create FreightRequest and Cargo
    req = FreightRequest.objects.create(
        organization=org, customer=customer, created_by=user, reference_code="REQ-001"
    )
    FreightRequestCargo.objects.create(
        freight_request=req,
        description="Frozen Meat",
        temperature_min_c=Decimal("-18.00"),
        temperature_max_c=Decimal("-12.00"),
    )

    # Create Stops (Pickup and Delivery)
    today = timezone.now().date()
    p_stop = FreightRequestStop.objects.create(
        freight_request=req,
        sequence=1,
        stop_type=FreightStopType.PICKUP.value,
        scheduled_date=today,
        window_start=datetime.time(8, 0),
        window_end=datetime.time(12, 0),
        city="Sao Paulo",
    )
    d_stop = FreightRequestStop.objects.create(
        freight_request=req,
        sequence=2,
        stop_type=FreightStopType.DELIVERY.value,
        scheduled_date=today,
        window_start=datetime.time(14, 0),
        window_end=datetime.time(18, 0),
        city="Campinas",
    )

    # Complete marketplace flow
    quote = FreightQuote.objects.create(
        organization=org, freight_request=req, created_by=user,
        reference_code="QT-001", status="DRAFT"
    )
    offer = FreightOffer.objects.create(
        organization=org, freight_request=req, freight_quote=quote,
        created_by=user, reference_code="OFR-001", status="PUBLISHED"
    )
    interest = FreightOfferInterest.objects.create(
        organization=org, offer=offer, carrier=carrier, driver=driver,
        vehicle=vehicle, status="CONFIRMED", expressed_at=timezone.now()
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest, organization=org, offer=offer,
        status="CONFIRMED", selected_by=user, selected_at=timezone.now()
    )

    # 2. Materialize operation
    operation = create_operation_from_selection(selection_id=str(selection.id), actor=user)

    # 3. Assert snapshots are populated
    assert operation.temperature_min_c == Decimal("-18.00")
    assert operation.temperature_max_c == Decimal("-12.00")

    op_d_stop = operation.stops.get(stop_type=FreightStopType.DELIVERY.value)
    assert op_d_stop.window_start == datetime.time(14, 0)
    assert op_d_stop.window_end == datetime.time(18, 0)

    # 4. Assert SLA is computed correctly from local snapshots
    result = SLAService.compute(operation)
    assert result.state in (SLAState.ON_TIME, SLAState.DELAYED)  # Depends on the current time vs 18:00 today
    assert result.planned_deadline is not None

    # 5. Snapshot Immutability check
    # Change the original commercial request limits and windows
    req.cargo.temperature_min_c = Decimal("0.00")
    req.cargo.save()
    d_stop.window_end = datetime.time(23, 0)
    d_stop.save()

    # Verify operation snapshot remains untouched
    assert operation.temperature_min_c == Decimal("-18.00")
    op_d_stop.refresh_from_db()
    assert op_d_stop.window_end == datetime.time(18, 0)

    # 6. Evaluate Thermal Readings Excursions
    # reading within bounds (-15C)
    reading, dup = record_thermal_reading(
        operation_id=str(operation.id),
        device_id="sensor-001",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("-15.00"),
        actor=user,
    )
    assert not ThermalExcursion.objects.filter(operation=operation).exists()

    # reading below min (-20C) -> Excursion BELOW_MIN
    record_thermal_reading(
        operation_id=str(operation.id),
        device_id="sensor-001",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("-20.00"),
        actor=user,
    )
    excursions = ThermalExcursion.objects.filter(operation=operation)
    assert excursions.count() == 1
    assert excursions.first().direction == "BELOW_MIN"
    assert excursions.first().status == "ACTIVE"

@pytest.mark.django_db
def test_contracted_route_operation_sla_and_thermal(setup_data):
    org = setup_data["org"]
    user = setup_data["user"]
    carrier = setup_data["carrier"]
    driver = setup_data["driver"]
    vehicle = setup_data["vehicle"]
    customer = setup_data["customer"]

    # 1. Create ContractedRoute with limits and load_type
    route = ContractedRoute.objects.create(
        organization=org,
        customer=customer,
        carrier=carrier,
        name="Campinas Route",
        status="ACTIVE",
        valid_from=timezone.now().date(),
        valid_until=timezone.now().date() + datetime.timedelta(days=30),
        load_type="LTL",
        preferred_driver=driver,
        preferred_vehicle=vehicle,
        temperature_min_c=Decimal("2.00"),
        temperature_max_c=Decimal("8.00"),
    )

    ContractedRouteStop.objects.create(
        organization=org,
        contracted_route=route,
        sequence=1,
        stop_type=FreightStopType.PICKUP.value,
        window_start=datetime.time(8, 0),
        window_end=datetime.time(12, 0),
        city="Sao Paulo",
    )
    ContractedRouteStop.objects.create(
        organization=org,
        contracted_route=route,
        sequence=2,
        stop_type=FreightStopType.DELIVERY.value,
        window_start=datetime.time(14, 0),
        window_end=datetime.time(18, 0),
        city="Campinas",
    )

    # Create Occurrence
    occurrence = ContractedRouteOccurrence.objects.create(
        organization=org,
        contracted_route=route,
        occurrence_date=timezone.now().date(),
        status="PLANNED",
    )

    # 2. Materialize
    operation = materialize_contracted_route_occurrence(occurrence_id=str(occurrence.id), actor=user)

    # 3. Assert snapshots populated
    assert operation.selection is None
    assert operation.source_type == OperationSource.CONTRACTED_ROUTE.value
    assert operation.load_type == "LTL"
    assert operation.temperature_min_c == Decimal("2.00")
    assert operation.temperature_max_c == Decimal("8.00")

    op_d_stop = operation.stops.get(stop_type=FreightStopType.DELIVERY.value)
    assert op_d_stop.window_start == datetime.time(14, 0)
    assert op_d_stop.window_end == datetime.time(18, 0)

    # 4. Assert SLA is computed correctly from local snapshots without marketplace
    result = SLAService.compute(operation)
    assert result.state is not None
    assert result.planned_deadline is not None

    # 5. Evaluate Thermal Readings Excursions (without selection)
    # reading within bounds (5C)
    record_thermal_reading(
        operation_id=str(operation.id),
        device_id="sensor-002",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("5.00"),
        actor=user,
    )
    assert not ThermalExcursion.objects.filter(operation=operation).exists()

    # reading above max (10C) -> Excursion ABOVE_MAX
    record_thermal_reading(
        operation_id=str(operation.id),
        device_id="sensor-002",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("10.00"),
        actor=user,
    )
    excursions = ThermalExcursion.objects.filter(operation=operation)
    assert excursions.count() == 1
    assert excursions.first().direction == "ABOVE_MAX"
    assert excursions.first().status == "ACTIVE"
