from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from src.compliance.domain.enums import DocumentStatus
from src.drivers.domain.enums import (
    DriverApprovalStatus,
    DriverAvailabilityStatus,
    DriverDocumentType,
    DriverEngagementType,
    DriverLicenseCategory,
    DriverStatus,
)
from src.drivers.domain.route_intent_enums import (
    DriverRouteIntentSource,
    DriverRouteIntentStatus,
    DriverRouteIntentType,
    RouteIntentCargoPreference,
)
from src.shared.domain.validators import normalize_document, validate_cpf
from src.shared.infrastructure.django.models import UUIDTimestampedModel


class Driver(UUIDTimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="driver_profiles",
        blank=True,
        null=True,
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="drivers",
    )
    full_name = models.CharField(max_length=180)
    birth_date = models.DateField(blank=True, null=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    mobile_phone = models.CharField(max_length=40, blank=True)
    document = models.CharField(max_length=40, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    street = models.CharField(max_length=180, blank=True)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=180, blank=True)
    district = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=2, default="BR", blank=True)
    driver_license_number = models.CharField(max_length=60, blank=True)
    driver_license_category = models.CharField(max_length=20, blank=True)
    driver_license_issue_state = models.CharField(max_length=2, blank=True)
    driver_license_expiration = models.DateField(blank=True, null=True)
    engagement_type = models.CharField(
        max_length=20,
        choices=[(kind.value, kind.value) for kind in DriverEngagementType],
        default=DriverEngagementType.OWNED,
    )
    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in DriverStatus],
        default=DriverStatus.PENDING,
    )
    approval_status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in DriverApprovalStatus],
        default=DriverApprovalStatus.PENDING,
    )
    availability_status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in DriverAvailabilityStatus],
        default=DriverAvailabilityStatus.OFFLINE,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_drivers",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["organization", "approval_status"]),
            models.Index(fields=["organization", "availability_status"]),
            models.Index(fields=["organization", "engagement_type"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document"],
                condition=~models.Q(document=""),
                name="unique_driver_document_per_organization_when_present",
            ),
            models.UniqueConstraint(
                fields=["organization", "driver_license_number"],
                condition=~models.Q(driver_license_number=""),
                name="unique_driver_license_per_organization_when_present",
            ),
        ]

    def clean(self):
        if self.document:
            self.document = normalize_document(self.document)
            if not validate_cpf(self.document):
                raise ValidationError({"document": "CPF inválido."})

        if self.driver_license_category and (
            self.driver_license_category not in [value.value for value in DriverLicenseCategory]
        ):
            raise ValidationError({"driver_license_category": "Categoria de CNH inválida."})

        if (
            self.approval_status == DriverApprovalStatus.APPROVED
            and self.driver_license_expiration
            and self.driver_license_expiration < timezone.localdate()
        ):
            raise ValidationError(
                {"driver_license_expiration": "CNH vencida não permite aprovação do motorista."}
            )

    @property
    def has_expired_driver_license(self) -> bool:
        return bool(
            self.driver_license_expiration and self.driver_license_expiration < timezone.localdate()
        )

    @property
    def masked_document(self) -> str:
        digits = normalize_document(self.document)
        if len(digits) != 11:
            return ""
        return f"{digits[:3]}.***.***-{digits[-2:]}"

    def save(self, *args, **kwargs):
        if self.document:
            self.document = normalize_document(self.document)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.full_name


class DriverDocument(UUIDTimestampedModel):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(
        max_length=40,
        choices=[(kind.value, kind.value) for kind in DriverDocumentType],
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
        related_name="reviewed_driver_documents",
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
        ordering = ["driver__full_name", "document_type", "-created_at"]
        indexes = [
            models.Index(fields=["driver", "status"]),
            models.Index(fields=["document_type", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["driver", "document_type"],
                condition=models.Q(
                    status__in=[
                        DocumentStatus.PENDING.value,
                        DocumentStatus.UNDER_REVIEW.value,
                        DocumentStatus.APPROVED.value,
                    ]
                ),
                name="unique_active_driver_document_type",
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
        return f"{self.driver} - {self.document_type}"


class DriverRouteIntent(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="driver_route_intents",
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.CASCADE,
        related_name="route_intents",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.SET_NULL,
        related_name="route_intents",
        blank=True,
        null=True,
    )
    intent_type = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in DriverRouteIntentType],
    )
    origin_city = models.CharField(max_length=80)
    origin_state = models.CharField(max_length=2)
    destination_city = models.CharField(max_length=80)
    destination_state = models.CharField(max_length=2)
    available_from = models.DateTimeField()
    available_until = models.DateTimeField()
    max_origin_deviation_km = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True
    )
    max_destination_deviation_km = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True
    )
    cargo_preference = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in RouteIntentCargoPreference],
        blank=True,
    )
    refrigeration_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in DriverRouteIntentStatus],
        default=DriverRouteIntentStatus.DRAFT,
    )
    source = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in DriverRouteIntentSource],
        default=DriverRouteIntentSource.BACKOFFICE,
    )
    notes = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_driver_route_intents",
        blank=True,
        null=True,
    )
    cancel_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-available_from", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["driver", "status"]),
            models.Index(fields=["vehicle", "status"]),
            models.Index(fields=["available_from", "available_until"]),
            models.Index(fields=["origin_state", "origin_city"]),
            models.Index(fields=["destination_state", "destination_city"]),
        ]

    def clean(self):
        for field_name in ("origin_state", "destination_state"):
            value = getattr(self, field_name, "")
            if value:
                setattr(self, field_name, value.upper())
                if len(value.upper()) != 2:
                    raise ValidationError({field_name: "UF deve ter 2 caracteres."})
        if self.available_from and self.available_until:
            if self.available_until <= self.available_from:
                raise ValidationError(
                    {"available_until": "Disponível até deve ser posterior a disponível de."}
                )
        if self.driver_id and self.organization_id:
            if self.driver.organization_id != self.organization_id:
                raise ValidationError({"driver": "Motorista fora da organização."})
        if self.vehicle_id and self.driver_id:
            if self.vehicle.organization_id != self.driver.organization_id:
                raise ValidationError({"vehicle": "Veículo fora da organização do motorista."})

    def save(self, *args, **kwargs):
        if self.origin_state:
            self.origin_state = self.origin_state.upper()
        if self.destination_state:
            self.destination_state = self.destination_state.upper()
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return bool(self.available_until and self.available_until <= timezone.now())

    @property
    def route_label(self) -> str:
        return f"{self.origin_city}/{self.origin_state} → {self.destination_city}/{self.destination_state}"

    def __str__(self) -> str:
        return f"{self.driver} · {self.route_label}"
