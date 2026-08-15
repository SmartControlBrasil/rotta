import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from src.compliance.domain.enums import DocumentStatus
from src.shared.infrastructure.django.models import UUIDTimestampedModel
from src.vehicles.domain.enums import (
    RefrigerationControlType,
    VehicleBodyType,
    VehicleCargoProfile,
    VehicleDocumentType,
    VehicleOperationalStatus,
    VehicleOwnershipType,
    VehicleStatus,
    VehicleType,
)


def normalize_plate(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def normalize_renavam(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def validate_renavam(value: str) -> bool:
    renavam = normalize_renavam(value)
    if len(renavam) != 11:
        return False
    if len(set(renavam)) == 1:
        return False
    return True


PLATE_REGEX = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")


class Vehicle(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    plate = models.CharField(max_length=12)
    renavam = models.CharField(max_length=20, blank=True)
    chassis = models.CharField(max_length=40, blank=True)
    vehicle_type = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleType],
    )
    body_type = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleBodyType],
        blank=True,
    )
    cargo_profile = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleCargoProfile],
        default=VehicleCargoProfile.DRY_CARGO,
    )
    ownership_type = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleOwnershipType],
        default=VehicleOwnershipType.OWNED,
    )
    brand = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    year = models.PositiveSmallIntegerField(blank=True, null=True)
    model_year = models.PositiveSmallIntegerField(blank=True, null=True)
    color = models.CharField(max_length=40, blank=True)
    state = models.CharField(max_length=2, blank=True)
    capacity_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    gross_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    capacity_volume_m3 = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    max_length_m = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    max_width_m = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    max_height_m = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    odometer_km = models.PositiveIntegerField(blank=True, null=True)
    refrigerated = models.BooleanField(default=False)
    closed_box = models.BooleanField(default=False)
    open_body = models.BooleanField(default=False)
    tail_lift = models.BooleanField(default=False)
    helper_available = models.BooleanField(default=False)
    hazardous_compatible = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in VehicleStatus],
        default=VehicleStatus.PENDING_APPROVAL,
    )
    operational_status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in VehicleOperationalStatus],
        default=VehicleOperationalStatus.UNAVAILABLE,
    )

    class Meta:
        ordering = ["plate"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "operational_status"]),
            models.Index(fields=["vehicle_type"]),
            models.Index(fields=["body_type"]),
            models.Index(fields=["cargo_profile"]),
            models.Index(fields=["plate"]),
            models.Index(fields=["state"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "plate"],
                name="unique_vehicle_plate_per_organization",
            ),
            models.UniqueConstraint(
                fields=["organization", "renavam"],
                condition=~models.Q(renavam=""),
                name="unique_vehicle_renavam_per_organization_when_present",
            ),
            models.UniqueConstraint(
                fields=["organization", "chassis"],
                condition=~models.Q(chassis=""),
                name="unique_vehicle_chassis_per_organization_when_present",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_weight_kg__gte=0) | models.Q(capacity_weight_kg=None),
                name="vehicle_capacity_weight_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(gross_weight_kg__gte=0) | models.Q(gross_weight_kg=None),
                name="vehicle_gross_weight_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_volume_m3__gte=0) | models.Q(capacity_volume_m3=None),
                name="vehicle_capacity_volume_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(max_length_m__gte=0) | models.Q(max_length_m=None),
                name="vehicle_max_length_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(max_width_m__gte=0) | models.Q(max_width_m=None),
                name="vehicle_max_width_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(max_height_m__gte=0) | models.Q(max_height_m=None),
                name="vehicle_max_height_non_negative",
            ),
        ]

    def clean(self):
        self.plate = normalize_plate(self.plate)
        if not self.plate:
            raise ValidationError({"plate": "Placa é obrigatória."})
        if not PLATE_REGEX.match(self.plate):
            raise ValidationError(
                {"plate": "Placa inválida. Use padrão brasileiro antigo ou Mercosul."}
            )

        if self.renavam:
            self.renavam = normalize_renavam(self.renavam)
            if not validate_renavam(self.renavam):
                raise ValidationError({"renavam": "RENAVAM inválido."})

        if self.state:
            self.state = self.state.upper()
            if len(self.state) != 2:
                raise ValidationError({"state": "UF deve ter 2 caracteres."})

        if self.model_year and self.year and self.model_year < self.year - 1:
            raise ValidationError(
                {"model_year": "Ano modelo inválido em relação ao ano de fabricação."}
            )

        if self.cargo_profile in {
            VehicleCargoProfile.REFRIGERATED_CARGO,
            VehicleCargoProfile.BOTH,
        }:
            self.refrigerated = True

    def save(self, *args, **kwargs):
        self.plate = normalize_plate(self.plate)
        self.renavam = normalize_renavam(self.renavam)
        if self.state:
            self.state = self.state.upper()
        super().save(*args, **kwargs)

    @property
    def masked_renavam(self) -> str:
        if not self.renavam:
            return ""
        digits = normalize_renavam(self.renavam)
        if len(digits) < 4:
            return "***"
        return f"{digits[:3]}***{digits[-2:]}"

    def __str__(self) -> str:
        return self.plate


class DriverVehicleAssignment(UUIDTimestampedModel):
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="vehicle_assignments",
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="driver_assignments"
    )
    active = models.BooleanField(default=True)
    primary = models.BooleanField(default=False)
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ["-active", "-primary", "-valid_from"]
        indexes = [
            models.Index(fields=["driver", "active"]),
            models.Index(fields=["vehicle", "active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(valid_until=None) | models.Q(valid_until__gte=models.F("valid_from"))
                ),
                name="driver_vehicle_assignment_valid_period",
            ),
            models.UniqueConstraint(
                fields=["driver"],
                condition=models.Q(active=True, primary=True),
                name="unique_active_primary_vehicle_per_driver",
            ),
            models.UniqueConstraint(
                fields=["vehicle"],
                condition=models.Q(active=True, primary=True),
                name="unique_active_primary_driver_per_vehicle",
            ),
            models.UniqueConstraint(
                fields=["driver", "vehicle", "valid_from"],
                name="unique_driver_vehicle_assignment_start",
            ),
        ]

    def clean(self):
        if (
            self.vehicle_id
            and self.driver_id
            and self.vehicle.organization_id != self.driver.organization_id
        ):
            raise ValidationError(
                {
                    "vehicle": (
                        "Motorista e veículo precisam pertencer à mesma organização nesta fase."
                    )
                }
            )
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError(
                {"valid_until": "Fim da vigência não pode ser anterior ao início."}
            )

    def __str__(self) -> str:
        return f"{self.driver} -> {self.vehicle}"


class RefrigerationProfile(UUIDTimestampedModel):
    vehicle = models.OneToOneField(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="refrigeration_profile",
    )
    has_refrigeration_unit = models.BooleanField(default=True)
    unit_manufacturer = models.CharField(max_length=80, blank=True)
    unit_model = models.CharField(max_length=80, blank=True)
    temperature_min_c = models.DecimalField(max_digits=5, decimal_places=2)
    temperature_max_c = models.DecimalField(max_digits=5, decimal_places=2)
    default_setpoint_c = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    control_type = models.CharField(
        max_length=20,
        choices=[(value.value, value.value) for value in RefrigerationControlType],
        default=RefrigerationControlType.DIGITAL,
    )
    last_maintenance_date = models.DateField(blank=True, null=True)
    next_maintenance_date = models.DateField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["next_maintenance_date"]),
            models.Index(fields=["control_type"]),
        ]

    def clean(self):
        if self.temperature_min_c >= self.temperature_max_c:
            raise ValidationError(
                {"temperature_max_c": "Faixa de temperatura inválida: min deve ser menor que max."}
            )
        if self.default_setpoint_c is not None and not (
            self.temperature_min_c <= self.default_setpoint_c <= self.temperature_max_c
        ):
            raise ValidationError(
                {"default_setpoint_c": "Setpoint deve estar dentro da faixa mínima e máxima."}
            )
        if (
            self.last_maintenance_date
            and self.next_maintenance_date
            and self.next_maintenance_date < self.last_maintenance_date
        ):
            raise ValidationError(
                {"next_maintenance_date": "Próxima manutenção não pode ser anterior à última."}
            )

    def __str__(self) -> str:
        return f"Refrigeração {self.vehicle.plate}"


class VehicleDocument(UUIDTimestampedModel):
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    document_type = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleDocumentType],
    )
    storage_key = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in DocumentStatus],
        default=DocumentStatus.PENDING,
    )
    issue_date = models.DateField(blank=True, null=True)
    expiration_date = models.DateField(blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_vehicle_documents",
        blank=True,
        null=True,
    )
    rejection_reason = models.TextField(blank=True)
    replaced_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="replaces",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["vehicle__plate", "document_type", "-created_at"]
        indexes = [
            models.Index(fields=["vehicle", "status"]),
            models.Index(fields=["document_type", "status"]),
            models.Index(fields=["expiration_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle", "document_type"],
                condition=models.Q(
                    status__in=[
                        DocumentStatus.PENDING.value,
                        DocumentStatus.UNDER_REVIEW.value,
                        DocumentStatus.APPROVED.value,
                    ]
                ),
                name="unique_active_vehicle_document_type",
            )
        ]

    def clean(self):
        if self.expiration_date and self.expiration_date < timezone.localdate():
            if self.status == DocumentStatus.APPROVED.value:
                raise ValidationError(
                    {"expiration_date": "Documento vencido não pode permanecer aprovado."}
                )

    @property
    def is_expired(self) -> bool:
        return bool(self.expiration_date and self.expiration_date < timezone.localdate())

    def __str__(self) -> str:
        return f"{self.vehicle.plate} - {self.document_type}"
