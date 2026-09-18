import pytest
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from src.freights.domain.enums import (
    OperationStatus,
    ThermalReadingQuality,
    ThermalReadingValidity,
    ThermalExcursionStatus,
    ThermalExcursionDirection,
)
from src.freights.infrastructure.django.models import (
    ThermalReading,
    ThermalExcursion,
    FreightOperation,
)
from src.freights.application.operation_services import record_thermal_reading
from tests.test_api_v1_driver_operations import (
    make_operation,
    generate_access_token,
    org_a,
    org_b,
    user_a,
    user_b,
    driver_a,
    driver_b,
    rbac_ready,
)


@pytest.fixture
def base_op(db, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "T")
    # Set cargo temp control limits
    cargo = op.selection.offer.freight_request.cargo
    cargo.temperature_min_c = Decimal("2.00")
    cargo.temperature_max_c = Decimal("8.00")
    cargo.save()
    # Update operational snapshot limits
    op.temperature_min_c = Decimal("2.00")
    op.temperature_max_c = Decimal("8.00")
    op.save()
    return op


@pytest.mark.django_db
def test_thermal_reading_creation_and_timestamps(base_op, user_a):
    ts = timezone.now() - timezone.timedelta(minutes=10)
    reading, duplicate = record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts,
        temperature_c=Decimal("5.50"),
        actor=user_a
    )
    assert duplicate is False
    assert reading.device_id == "sensor-1"
    assert reading.sensor_timestamp == ts
    assert reading.server_timestamp is not None
    assert reading.temperature_c == Decimal("5.50")
    assert reading.validity == ThermalReadingValidity.VALID.value
    assert reading.quality == ThermalReadingQuality.VALID.value


@pytest.mark.django_db
def test_thermal_reading_future_rejected(base_op, user_a):
    future_ts = timezone.now() + timezone.timedelta(minutes=10)
    with pytest.raises(ValidationError):
        record_thermal_reading(
            operation_id=base_op.id,
            device_id="sensor-1",
            sensor_timestamp=future_ts,
            temperature_c=Decimal("5.50"),
            actor=user_a
        )


@pytest.mark.django_db
def test_thermal_reading_stale_detected(base_op, user_a):
    stale_ts = timezone.now() - timezone.timedelta(hours=25)
    reading, duplicate = record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=stale_ts,
        temperature_c=Decimal("5.50"),
        actor=user_a
    )
    assert reading.validity == ThermalReadingValidity.STALE.value
    # Stale readings must not generate excursions
    assert ThermalExcursion.objects.filter(operation=base_op).exists() is False


@pytest.mark.django_db
def test_thermal_reading_no_limits(db, org_a, user_a, driver_a):
    op = make_operation(org_a, user_a, driver_a, "N")
    # No temperature limits set
    reading, duplicate = record_thermal_reading(
        operation_id=op.id,
        device_id="sensor-1",
        sensor_timestamp=timezone.now(),
        temperature_c=Decimal("5.50"),
        actor=user_a
    )
    assert reading.validity == ThermalReadingValidity.VALID.value
    assert ThermalExcursion.objects.filter(operation=op).exists() is False


@pytest.mark.django_db
def test_thermal_reading_idempotency(base_op, user_a):
    ts = timezone.now()
    reading1, dup1 = record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts,
        temperature_c=Decimal("5.50"),
        client_event_id="evt-1",
        actor=user_a
    )
    assert dup1 is False

    # Retry with same client_event_id
    reading2, dup2 = record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts,
        temperature_c=Decimal("6.00"),
        client_event_id="evt-1",
        actor=user_a
    )
    assert dup2 is True
    assert reading1.id == reading2.id
    assert reading2.temperature_c == Decimal("5.50")  # wasn't updated


@pytest.mark.django_db
def test_thermal_excursion_above_max(base_op, user_a):
    ts = timezone.now()
    # 9.50 is above max limit of 8.00
    reading, duplicate = record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts,
        temperature_c=Decimal("9.50"),
        actor=user_a
    )
    excursion = ThermalExcursion.objects.filter(operation=base_op, status=ThermalExcursionStatus.ACTIVE.value).first()
    assert excursion is not None
    assert excursion.direction == ThermalExcursionDirection.ABOVE_MAX.value
    assert excursion.min_observed == Decimal("9.50")
    assert excursion.max_observed == Decimal("9.50")
    assert excursion.sensor_id == "sensor-1"

    # Continue excursion with higher temperature
    record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts + timezone.timedelta(minutes=1),
        temperature_c=Decimal("11.20"),
        actor=user_a
    )
    excursion.refresh_from_db()
    assert excursion.max_observed == Decimal("11.20")
    assert excursion.min_observed == Decimal("9.50")
    # ensure no new excursion is created
    assert ThermalExcursion.objects.filter(operation=base_op).count() == 1


@pytest.mark.django_db
def test_thermal_excursion_below_min(base_op, user_a):
    ts = timezone.now()
    # 1.20 is below min limit of 2.00
    reading, duplicate = record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts,
        temperature_c=Decimal("1.20"),
        actor=user_a
    )
    excursion = ThermalExcursion.objects.filter(operation=base_op, status=ThermalExcursionStatus.ACTIVE.value).first()
    assert excursion is not None
    assert excursion.direction == ThermalExcursionDirection.BELOW_MIN.value
    assert excursion.min_observed == Decimal("1.20")
    assert excursion.max_observed == Decimal("1.20")


@pytest.mark.django_db
def test_thermal_excursion_resolution_and_new_excursion(base_op, user_a):
    ts = timezone.now()
    # 1. Start above max
    record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts,
        temperature_c=Decimal("9.50"),
        actor=user_a
    )
    excursion = ThermalExcursion.objects.filter(operation=base_op, status=ThermalExcursionStatus.ACTIVE.value).first()
    assert excursion is not None

    # 2. Return to range (5.00 is between 2.00 and 8.00)
    record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts + timezone.timedelta(minutes=1),
        temperature_c=Decimal("5.00"),
        actor=user_a
    )
    excursion.refresh_from_db()
    assert excursion.status == ThermalExcursionStatus.RESOLVED.value
    assert excursion.ended_at is not None

    # 3. Excursion closed, no active excursion now
    assert ThermalExcursion.objects.filter(operation=base_op, status=ThermalExcursionStatus.ACTIVE.value).exists() is False

    # 4. Trigger below min
    record_thermal_reading(
        operation_id=base_op.id,
        device_id="sensor-1",
        sensor_timestamp=ts + timezone.timedelta(minutes=2),
        temperature_c=Decimal("0.50"),
        actor=user_a
    )
    new_excursion = ThermalExcursion.objects.filter(operation=base_op, status=ThermalExcursionStatus.ACTIVE.value).first()
    assert new_excursion is not None
    assert new_excursion.direction == ThermalExcursionDirection.BELOW_MIN.value
    assert new_excursion.id != excursion.id


@pytest.mark.django_db
def test_thermal_reading_api_flow(client, base_op, user_a, driver_b, user_b):
    token_a = generate_access_token(user_a)
    token_b = generate_access_token(user_b)
    url = reverse("api_v1:record_thermal_reading", args=[base_op.id])

    # 1. Test Authorization: driver_b cannot log to base_op (which belongs to driver_a)
    response = client.post(
        url,
        data={
            "sensor_id": "device-api",
            "sensor_timestamp": timezone.now().isoformat(),
            "temperature_c": 5.0,
            "client_event_id": "evt-api-1",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_b}"
    )
    assert response.status_code == 404

    # 2. Test valid ingestion by assigned driver
    ts = timezone.now()
    response = client.post(
        url,
        data={
            "sensor_id": "device-api",
            "sensor_timestamp": ts.isoformat(),
            "temperature_c": 1.5, # triggers below min
            "client_event_id": "evt-api-2",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 201
    data = response.json()
    assert data["created"] is True
    assert data["duplicate"] is False
    assert data["temperature_c"] == 1.5
    assert data["within_range"] is False
    assert data["active_excursion"] is not None
    assert data["active_excursion"]["direction"] == "BELOW_MIN"

    # 3. Test duplicate retry (idempotency)
    response = client.post(
        url,
        data={
            "sensor_id": "device-api",
            "sensor_timestamp": ts.isoformat(),
            "temperature_c": 1.5,
            "client_event_id": "evt-api-2",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] is False
    assert data["duplicate"] is True

    # 4. Test detail view thermal summary reflects excursion
    detail_url = reverse("api_v1:driver_operation_detail", args=[base_op.id])
    detail_response = client.get(
        detail_url,
        HTTP_AUTHORIZATION=f"Bearer {token_a}"
    )
    assert detail_response.status_code == 200
    detail_data = detail_response.json()
    summary = detail_data["thermal_summary"]
    assert summary["latest_temperature_c"] == 1.5
    assert summary["active_excursion"] is True
    assert summary["active_excursion_direction"] == "BELOW_MIN"
    assert summary["excursion_started_at"] is not None
