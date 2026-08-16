# tests/test_freight_logistics_enrichment.py
"""Tests for Phase 1 logistics enrichment:
- LoadType on FreightOperation (nullable, explicit only)
- ETA / delay_minutes on FreightOperation (nullable, no sentinel)
- ThermalReading model (independent of GPS, device_id required)
- SLAService (deterministic, no persistence, no artificial ETAs)
"""

import datetime
import pytest
from decimal import Decimal
from django.utils import timezone
from unittest.mock import MagicMock, patch

from src.freights.domain.enums import (
    LoadType,
    OperationStatus,
    FreightStopType,
)
from src.freights.application.sla_service import SLAService, SLAState, SLAResult


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_operation(**kwargs):
    """Create a lightweight mock of FreightOperation for SLAService unit tests."""
    op = MagicMock()
    op.load_type = kwargs.get("load_type", None)
    op.eta = kwargs.get("eta", None)
    op.delay_minutes = kwargs.get("delay_minutes", None)
    op.assigned_at = kwargs.get("assigned_at", None)
    op.started_at = kwargs.get("started_at", None)
    op.completed_at = kwargs.get("completed_at", None)
    op.status = kwargs.get("status", OperationStatus.ASSIGNED.value)
    # selection.offer.freight_request.stops chain
    op.selection.offer.freight_request.stops.filter.return_value.order_by.return_value.first.return_value = None
    return op


# ─────────────────────────────────────────────────────────────────────────────
# LoadType enum tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadTypeEnum:
    def test_values_are_ftl_ltl(self):
        assert LoadType.FTL == "FTL"
        assert LoadType.LTL == "LTL"

    def test_only_two_values(self):
        assert set(LoadType) == {LoadType.FTL, LoadType.LTL}


# ─────────────────────────────────────────────────────────────────────────────
# FreightOperation new fields — DB integration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base_operation(db):
    """Create a minimal FreightOperation to test new nullable fields."""
    from django.contrib.auth import get_user_model
    from src.organizations.infrastructure.django.models import Organization, Membership
    from src.carriers.infrastructure.django.models import CarrierProfile
    from src.customers.infrastructure.django.models import Customer
    from src.freights.infrastructure.django.models import (
        FreightRequest,
        FreightQuote,
        FreightOffer,
        FreightOfferInterest,
        FreightOfferSelection,
        FreightOperation,
    )

    User = get_user_model()
    org = Organization.objects.create(name="LogisticsOrg")
    user = User.objects.create_user(username="logtest", password="x", is_staff=True)
    Membership.objects.create(user=user, organization=org)

    carrier = CarrierProfile.objects.create(
        organization=org, tenant=org, trade_name="Carrier", status="ACTIVE"
    )
    from src.drivers.infrastructure.django.models import Driver
    driver = Driver.objects.create(organization=org, full_name="Driver")
    from src.vehicles.infrastructure.django.models import Vehicle
    vehicle = Vehicle.objects.create(organization=org, plate="XYZ9999", vehicle_type="TRUCK")

    customer = Customer.objects.create(
        organization=org,
        legal_name="Customer",
        document_number="99999999999",
        email="c@c.com",
    )
    req = FreightRequest.objects.create(
        organization=org, customer=customer, created_by=user, reference_code="REQ-LOG"
    )
    quote = FreightQuote.objects.create(
        organization=org, freight_request=req, created_by=user,
        reference_code="QT-LOG", status="DRAFT",
    )
    offer = FreightOffer.objects.create(
        organization=org, freight_request=req, freight_quote=quote,
        created_by=user, reference_code="OFR-LOG", status="DRAFT",
    )
    interest = FreightOfferInterest.objects.create(
        organization=org, offer=offer, carrier=carrier, driver=driver,
        vehicle=vehicle, status="CONFIRMED", expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest, organization=org, offer=offer,
        status="CONFIRMED", selected_by=user, selected_at=timezone.now(),
    )
    op = FreightOperation.objects.create(
        organization=org,
        selection=selection,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status=OperationStatus.ASSIGNED.value,
    )
    return op


@pytest.mark.django_db
def test_operation_load_type_defaults_null(base_operation):
    """load_type must be null by default (never inferred)."""
    assert base_operation.load_type is None


@pytest.mark.django_db
def test_operation_load_type_can_be_set_explicitly(base_operation):
    """load_type can be set to FTL or LTL explicitly."""
    base_operation.load_type = LoadType.FTL.value
    base_operation.save()
    base_operation.refresh_from_db()
    assert base_operation.load_type == LoadType.FTL.value


@pytest.mark.django_db
def test_operation_load_type_ltl(base_operation):
    base_operation.load_type = LoadType.LTL.value
    base_operation.save()
    base_operation.refresh_from_db()
    assert base_operation.load_type == LoadType.LTL.value


@pytest.mark.django_db
def test_operation_eta_defaults_null(base_operation):
    """eta must be null by default."""
    assert base_operation.eta is None


@pytest.mark.django_db
def test_operation_eta_can_be_set(base_operation):
    future = timezone.now() + datetime.timedelta(hours=4)
    base_operation.eta = future
    base_operation.save()
    base_operation.refresh_from_db()
    assert base_operation.eta is not None


@pytest.mark.django_db
def test_operation_delay_minutes_defaults_null(base_operation):
    """delay_minutes must be null by default — no sentinel values."""
    assert base_operation.delay_minutes is None


@pytest.mark.django_db
def test_operation_delay_minutes_can_be_set(base_operation):
    base_operation.delay_minutes = 45
    base_operation.save()
    base_operation.refresh_from_db()
    assert base_operation.delay_minutes == 45


# ─────────────────────────────────────────────────────────────────────────────
# ThermalReading model — DB integration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_thermal_reading_created_for_operation(base_operation):
    """ThermalReading requires operation and device_id; tracking_session is optional."""
    from src.freights.infrastructure.django.models import ThermalReading

    reading = ThermalReading.objects.create(
        operation=base_operation,
        device_id="sensor-abc-001",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("4.20"),
        is_valid=True,
    )
    assert reading.pk is not None
    assert reading.tracking_session is None  # independent of GPS


@pytest.mark.django_db
def test_thermal_reading_unique_per_op_device_ts(base_operation):
    """Duplicate (operation, device_id, sensor_timestamp) is rejected."""
    from django.db import IntegrityError
    from src.freights.infrastructure.django.models import ThermalReading

    ts = timezone.now()
    ThermalReading.objects.create(
        operation=base_operation,
        device_id="sensor-dup",
        sensor_timestamp=ts,
        temperature_c=Decimal("3.50"),
    )
    with pytest.raises(IntegrityError):
        ThermalReading.objects.create(
            operation=base_operation,
            device_id="sensor-dup",
            sensor_timestamp=ts,
            temperature_c=Decimal("3.60"),
        )


@pytest.mark.django_db
def test_thermal_reading_different_sensors_same_ts(base_operation):
    """Different device_ids on same timestamp are independent readings."""
    from src.freights.infrastructure.django.models import ThermalReading

    ts = timezone.now()
    ThermalReading.objects.create(
        operation=base_operation, device_id="sensor-A",
        sensor_timestamp=ts, temperature_c=Decimal("2.00"),
    )
    ThermalReading.objects.create(
        operation=base_operation, device_id="sensor-B",
        sensor_timestamp=ts, temperature_c=Decimal("2.10"),
    )
    assert ThermalReading.objects.filter(operation=base_operation).count() == 2


@pytest.mark.django_db
def test_thermal_reading_metadata_optional(base_operation):
    from src.freights.infrastructure.django.models import ThermalReading

    reading = ThermalReading.objects.create(
        operation=base_operation,
        device_id="sensor-meta",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("-18.00"),
        metadata={"humidity": 85, "battery_pct": 72},
    )
    reading.refresh_from_db()
    assert reading.metadata["humidity"] == 85


@pytest.mark.django_db
def test_thermal_reading_str(base_operation):
    from src.freights.infrastructure.django.models import ThermalReading

    ts = timezone.now()
    reading = ThermalReading.objects.create(
        operation=base_operation,
        device_id="sensor-str",
        sensor_timestamp=ts,
        temperature_c=Decimal("6.00"),
    )
    assert "sensor-str" in str(reading)
    assert "6.00" in str(reading)


# ─────────────────────────────────────────────────────────────────────────────
# SLAService — pure unit tests (no DB, no real models)
# ─────────────────────────────────────────────────────────────────────────────

class TestSLAServiceUnknown:
    def test_no_data_returns_unknown(self):
        op = _make_operation()
        result = SLAService.compute(op)
        assert result.state == SLAState.UNKNOWN
        assert result.planned_deadline is None


class TestSLAServiceExplicitDelayMinutes:
    def test_zero_delay_is_on_time(self):
        op = _make_operation(delay_minutes=0)
        result = SLAService.compute(op)
        assert result.state == SLAState.ON_TIME

    def test_negative_delay_is_on_time(self):
        op = _make_operation(delay_minutes=-10)
        result = SLAService.compute(op)
        assert result.state == SLAState.ON_TIME

    def test_positive_delay_is_delayed(self):
        op = _make_operation(delay_minutes=60)
        result = SLAService.compute(op)
        assert result.state == SLAState.DELAYED
        assert result.computed_delay_minutes == 60


class TestSLAServiceWithETA:
    def _deadline(self):
        return timezone.now() + datetime.timedelta(hours=2)

    def _make_op_with_deadline(self, eta_offset_minutes):
        """Create a mock operation where the delivery stop deadline is `now + 2h`
        and eta = deadline + eta_offset_minutes.

        The deadline is constructed without microseconds so that
        _planned_deadline(combine(date, time)) produces the identical value.
        """
        tz = timezone.get_current_timezone()
        now_local = datetime.datetime.now(tz).replace(microsecond=0, second=0)
        deadline_local = now_local + datetime.timedelta(hours=2)

        op = MagicMock()
        op.load_type = None
        op.delay_minutes = None
        op.assigned_at = None
        op.started_at = None
        op.completed_at = None

        # eta is deadline + offset, also without microseconds.
        eta_local = deadline_local + datetime.timedelta(minutes=eta_offset_minutes)
        op.eta = eta_local  # already tz-aware (datetime.now(tz))

        # stop window_end must be the time component only (no microseconds)
        stop = MagicMock()
        stop.scheduled_date = deadline_local.date()
        stop.window_end = deadline_local.time()  # no microseconds — replaced above
        (op.selection.offer.freight_request.stops
           .filter.return_value.order_by.return_value.first.return_value) = stop
        return op

    def test_eta_before_deadline_is_on_time(self):
        op = self._make_op_with_deadline(eta_offset_minutes=-30)
        result = SLAService.compute(op)
        assert result.state == SLAState.ON_TIME

    def test_eta_slightly_past_deadline_is_at_risk(self):
        # 20 min past deadline → AT_RISK (threshold is 30)
        op = self._make_op_with_deadline(eta_offset_minutes=20)
        result = SLAService.compute(op)
        assert result.state == SLAState.AT_RISK

    def test_eta_well_past_deadline_is_delayed(self):
        # 60 min past deadline → DELAYED
        op = self._make_op_with_deadline(eta_offset_minutes=60)
        result = SLAService.compute(op)
        assert result.state == SLAState.DELAYED
        assert result.computed_delay_minutes == 60


class TestSLAServiceCompleted:
    def _make_completed_op(self, completed_offset_minutes):
        """Make a completed operation with a delivery stop window.

        `completed_offset_minutes` is the offset of the deadline relative to now.
        Positive = deadline is in the future (on time); negative = deadline already passed (late).
        """
        tz = timezone.get_current_timezone()
        now = datetime.datetime.now(tz).replace(microsecond=0)
        deadline_local = now + datetime.timedelta(minutes=completed_offset_minutes)

        op = MagicMock()
        op.load_type = None
        op.eta = None
        op.delay_minutes = None
        op.assigned_at = now - datetime.timedelta(hours=4)
        op.started_at = now - datetime.timedelta(hours=3)
        op.completed_at = now
        op.status = OperationStatus.DELIVERED.value

        stop = MagicMock()
        stop.scheduled_date = deadline_local.date()
        stop.window_end = deadline_local.time()
        (op.selection.offer.freight_request.stops
           .filter.return_value.order_by.return_value.first.return_value) = stop
        return op

    def test_completed_before_deadline_is_completed_on_time(self):
        # Deadline is 30 min in the future from now; completed_at = now → on time
        op = self._make_completed_op(completed_offset_minutes=30)
        result = SLAService.compute(op)
        assert result.state == SLAState.COMPLETED_ON_TIME

    def test_completed_after_deadline_is_completed_late(self):
        # Deadline was 30 min ago; completed_at = now → late
        op = self._make_completed_op(completed_offset_minutes=-30)
        result = SLAService.compute(op)
        assert result.state == SLAState.COMPLETED_LATE
        assert result.computed_delay_minutes is not None
        assert result.computed_delay_minutes > 0
