from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from src.carriers.domain.enums import (
    CarrierCargoProfile,
    CarrierDocumentType,
    CarrierStatus,
    CarrierVehicleLinkType,
)
from src.compliance.domain.enums import DocumentStatus
from src.shared.infrastructure.django.models import UUIDTimestampedModel


class CarrierProfile(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="carrier_profiles",
    )
    tenant = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="registered_carriers",
    )
    trade_name = models.CharField(max_length=180, blank=True)
    state_registration = models.CharField(max_length=40, blank=True)
    municipal_registration = models.CharField(max_length=40, blank=True)

    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    mobile_phone = models.CharField(max_length=40, blank=True)
    site = models.CharField(max_length=200, blank=True)

    # Address
    postal_code = models.CharField(max_length=20, blank=True)
    street = models.CharField(max_length=180, blank=True)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=180, blank=True)
    district = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=2, default="BR", blank=True)

    # ANTT (RNTRC) fields
    rntrc = models.CharField(max_length=40, blank=True)
    rntrc_category = models.CharField(max_length=40, blank=True)
    rntrc_expiration = models.DateField(null=True, blank=True)
    rntrc_status = models.CharField(max_length=40, blank=True)

    cargo_profile = models.CharField(
        max_length=20,
        choices=[(p.value, p.value) for p in CarrierCargoProfile],
        default=CarrierCargoProfile.DRY_CARGO,
    )
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in CarrierStatus],
        default=CarrierStatus.PROSPECT,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_carriers",
    )

    class Meta:
        ordering = ["trade_name", "organization__name"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "cargo_profile"]),
            models.Index(fields=["tenant", "rntrc"]),
            models.Index(fields=["owner"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "organization"],
                name="unique_tenant_carrier",
            ),
            models.UniqueConstraint(
                fields=["tenant", "rntrc"],
                condition=~models.Q(rntrc=""),
                name="unique_carrier_rntrc_per_tenant_when_present",
            ),
        ]

    def __str__(self) -> str:
        return self.trade_name or self.organization.name


class CarrierDriverLink(UUIDTimestampedModel):
    carrier = models.ForeignKey(
        CarrierProfile,
        on_delete=models.CASCADE,
        related_name="driver_links",
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="carrier_links",
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["carrier__trade_name", "driver__full_name"]
        indexes = [
            models.Index(fields=["carrier", "active"]),
            models.Index(fields=["driver", "active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "driver"],
                name="unique_driver_link_per_carrier",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.carrier_id
            and self.driver_id
            and self.carrier.tenant_id != self.driver.organization_id
        ):
            raise ValidationError(
                {
                    "driver": (
                        "Motorista precisa pertencer ao mesmo tenant operacional da transportadora."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.carrier} -> {self.driver}"


class CarrierVehicleLink(UUIDTimestampedModel):
    carrier = models.ForeignKey(
        CarrierProfile,
        on_delete=models.CASCADE,
        related_name="vehicle_links",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
        related_name="carrier_links",
    )
    link_type = models.CharField(
        max_length=20,
        choices=[(value.value, value.value) for value in CarrierVehicleLinkType],
        default=CarrierVehicleLinkType.OWNED,
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["carrier__trade_name", "vehicle__plate"]
        indexes = [
            models.Index(fields=["carrier", "active"]),
            models.Index(fields=["vehicle", "active"]),
            models.Index(fields=["link_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "vehicle"],
                name="unique_vehicle_link_per_carrier",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.carrier_id
            and self.vehicle_id
            and self.carrier.tenant_id != self.vehicle.organization_id
        ):
            raise ValidationError(
                {
                    "vehicle": (
                        "Veículo precisa pertencer ao mesmo tenant operacional da transportadora."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.carrier} -> {self.vehicle}"


class CarrierDocument(UUIDTimestampedModel):
    carrier = models.ForeignKey(
        CarrierProfile,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    document_type = models.CharField(
        max_length=40,
        choices=[(kind.value, kind.value) for kind in CarrierDocumentType],
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
        related_name="reviewed_carrier_documents",
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
        ordering = ["carrier__trade_name", "document_type", "-created_at"]
        indexes = [
            models.Index(fields=["carrier", "status"]),
            models.Index(fields=["document_type", "status"]),
            models.Index(fields=["expiration_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "document_type"],
                condition=models.Q(
                    status__in=[
                        DocumentStatus.PENDING.value,
                        DocumentStatus.UNDER_REVIEW.value,
                        DocumentStatus.APPROVED.value,
                    ]
                ),
                name="unique_active_carrier_document_type",
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
        return f"{self.carrier} - {self.document_type}"
