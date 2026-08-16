from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightCargoType,
    FreightRequestPriority,
    FreightRequestStatus,
    FreightStopType,
    OperationStatus,
    OperationEventOrigin,
    OperationEventType,
)
from src.freights.domain.matching_enums import (
    FreightOfferInterestStatus,
    FreightOfferInvitationStatus,
    FreightOfferSelectionStatus,
    InvitationDeclineReason,
    MarketplaceEventType,
    MatchEligibilityStatus,
    SelectionDeclineReason,
)
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.domain.quote_enums import (
    FreightPricingMethod,
    FreightQuoteChargeType,
    FreightQuoteStatus,
)
from src.shared.infrastructure.django.models import UUIDTimestampedModel
from src.vehicles.domain.enums import VehicleBodyType, VehicleType


class FreightRequestReferenceSequence(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="freight_request_sequences",
    )
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year"],
                name="unique_freight_request_sequence_per_org_year",
            )
        ]


class FreightRequest(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_requests",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="freight_requests",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_freight_requests",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="owned_freight_requests",
        blank=True,
        null=True,
    )
    reference_code = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=30,
        choices=[(status.value, status.value) for status in FreightRequestStatus],
        default=FreightRequestStatus.DRAFT,
    )
    priority = models.CharField(
        max_length=20,
        choices=[(priority.value, priority.value) for priority in FreightRequestPriority],
        default=FreightRequestPriority.NORMAL,
    )
    instructions = models.TextField(blank=True)
    handling_requirements = models.TextField(blank=True)
    hazardous_material = models.BooleanField(default=False)
    declared_cargo_value = models.DecimalField(
        max_digits=14, decimal_places=2, blank=True, null=True
    )
    currency = models.CharField(max_length=3, default="BRL", blank=True)
    vehicle_type_required = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleType],
        blank=True,
    )
    body_type_required = models.CharField(
        max_length=30,
        choices=[(kind.value, kind.value) for kind in VehicleBodyType],
        blank=True,
    )
    submitted_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_freight_requests",
        blank=True,
        null=True,
    )
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "customer"]),
            models.Index(fields=["owner"]),
            models.Index(fields=["reference_code"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference_code"],
                condition=~models.Q(reference_code=""),
                name="unique_freight_request_reference_per_organization",
            ),
        ]

    def clean(self):
        if self.customer_id and self.organization_id:
            if self.customer.organization_id != self.organization_id:
                raise ValidationError(
                    {"customer": "Cliente deve pertencer à mesma organização da solicitação."}
                )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    @property
    def pickup_stop(self):
        return (
            self.stops.filter(stop_type=FreightStopType.PICKUP.value).order_by("sequence").first()
        )

    @property
    def delivery_stop(self):
        return (
            self.stops.filter(stop_type=FreightStopType.DELIVERY.value).order_by("sequence").first()
        )

    def __str__(self) -> str:
        return self.reference_code or str(self.id)


class FreightRequestStop(UUIDTimestampedModel):
    freight_request = models.ForeignKey(
        FreightRequest,
        on_delete=models.CASCADE,
        related_name="stops",
    )
    sequence = models.PositiveSmallIntegerField(default=1)
    stop_type = models.CharField(
        max_length=20,
        choices=[(kind.value, kind.value) for kind in FreightStopType],
    )
    postal_code = models.CharField(max_length=20, blank=True)
    street = models.CharField(max_length=180, blank=True)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=180, blank=True)
    district = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=2, default="BR", blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    instructions = models.TextField(blank=True)
    scheduled_date = models.DateField(blank=True, null=True)
    window_start = models.TimeField(blank=True, null=True)
    window_end = models.TimeField(blank=True, null=True)

    class Meta:
        ordering = ["sequence", "stop_type"]
        indexes = [
            models.Index(fields=["freight_request", "stop_type"]),
            models.Index(fields=["freight_request", "sequence"]),
            models.Index(fields=["state"]),
            models.Index(fields=["city"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["freight_request", "sequence"],
                name="unique_freight_request_stop_sequence",
            ),
        ]

    def clean(self):
        if self.state:
            self.state = self.state.upper()
            if self.state and len(self.state) != 2:
                raise ValidationError({"state": "UF deve ter 2 caracteres."})
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValidationError({"window_end": "Fim da janela deve ser posterior ao início."})

    def save(self, *args, **kwargs):
        if self.state:
            self.state = self.state.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.stop_type} #{self.sequence} - {self.city}/{self.state}"


class FreightRequestCargo(UUIDTimestampedModel):
    freight_request = models.OneToOneField(
        FreightRequest,
        on_delete=models.CASCADE,
        related_name="cargo",
    )
    description = models.TextField(blank=True)
    cargo_type = models.CharField(
        max_length=40,
        choices=[(kind.value, kind.value) for kind in FreightCargoType],
        default=FreightCargoType.GENERAL_CARGO,
    )
    cargo_profile = models.CharField(
        max_length=30,
        choices=[(profile.value, profile.value) for profile in FreightCargoProfile],
        default=FreightCargoProfile.DRY_CARGO,
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=3, blank=True, null=True)
    volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, blank=True, null=True)
    package_count = models.PositiveIntegerField(blank=True, null=True)
    package_type = models.CharField(max_length=80, blank=True)
    temperature_min_c = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    temperature_max_c = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    target_temperature_c = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["cargo_profile"]),
            models.Index(fields=["cargo_type"]),
        ]

    def clean(self):
        if self.cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
            if self.temperature_min_c is not None and self.temperature_max_c is not None:
                if self.temperature_min_c >= self.temperature_max_c:
                    raise ValidationError(
                        {"temperature_max_c": "Temperatura mínima deve ser menor que a máxima."}
                    )
            if (
                self.target_temperature_c is not None
                and self.temperature_min_c is not None
                and self.temperature_max_c is not None
                and not (
                    self.temperature_min_c <= self.target_temperature_c <= self.temperature_max_c
                )
            ):
                raise ValidationError(
                    {"target_temperature_c": "Setpoint deve estar dentro da faixa térmica."}
                )
        elif self.cargo_profile == FreightCargoProfile.DRY_CARGO.value:
            if any(
                value is not None
                for value in (
                    self.temperature_min_c,
                    self.temperature_max_c,
                    self.target_temperature_c,
                )
            ):
                raise ValidationError(
                    {"cargo_profile": "Carga seca não deve informar requisitos térmicos."}
                )

        if self.weight_kg is not None and self.weight_kg < 0:
            raise ValidationError({"weight_kg": "Peso não pode ser negativo."})
        if self.volume_m3 is not None and self.volume_m3 < 0:
            raise ValidationError({"volume_m3": "Volume não pode ser negativo."})

    def __str__(self) -> str:
        return f"Carga {self.freight_request_id}"


class FreightQuoteReferenceSequence(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="freight_quote_sequences",
    )
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year"],
                name="unique_freight_quote_sequence_per_org_year",
            )
        ]


class FreightQuote(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_quotes",
    )
    freight_request = models.ForeignKey(
        FreightRequest,
        on_delete=models.PROTECT,
        related_name="quotes",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_freight_quotes",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="owned_freight_quotes",
        blank=True,
        null=True,
    )
    revision_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="revisions",
        blank=True,
        null=True,
    )
    reference_code = models.CharField(max_length=32, blank=True)
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=30,
        choices=[(status.value, status.value) for status in FreightQuoteStatus],
        default=FreightQuoteStatus.DRAFT,
    )
    pricing_method = models.CharField(
        max_length=20,
        choices=[(method.value, method.value) for method in FreightPricingMethod],
        default=FreightPricingMethod.MANUAL,
    )
    currency = models.CharField(max_length=3, default="BRL", blank=True)
    base_freight_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    additional_charges = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    insurance_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    customer_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valid_until = models.DateField(blank=True, null=True)
    estimated_distance_km = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    estimated_duration_hours = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True
    )
    premises_snapshot = models.JSONField(default=dict, blank=True)
    internal_notes = models.TextField(blank=True)
    customer_notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_freight_quotes",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="sent_freight_quotes",
        blank=True,
        null=True,
    )
    sent_at = models.DateTimeField(blank=True, null=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="rejected_freight_quotes",
        blank=True,
        null=True,
    )
    rejected_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_freight_quotes",
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True)
    submitted_for_review_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["freight_request", "version"]),
            models.Index(fields=["owner"]),
            models.Index(fields=["reference_code"]),
            models.Index(fields=["valid_until"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference_code"],
                condition=~models.Q(reference_code=""),
                name="unique_freight_quote_reference_per_organization",
            ),
            models.UniqueConstraint(
                fields=["freight_request", "version"],
                name="unique_freight_quote_version_per_request",
            ),
        ]

    def clean(self):
        if self.freight_request_id and self.organization_id:
            if self.freight_request.organization_id != self.organization_id:
                raise ValidationError(
                    {
                        "freight_request": (
                            "Solicitação deve pertencer à mesma organização da cotação."
                        )
                    }
                )
        if self.estimated_cost is not None and self.estimated_cost < 0:
            raise ValidationError({"estimated_cost": "Custo estimado não pode ser negativo."})
        if self.tax_amount is not None and self.tax_amount < 0:
            raise ValidationError({"tax_amount": "Imposto não pode ser negativo."})

    @property
    def gross_margin_amount(self):
        if self.estimated_cost is None:
            return None
        return self.customer_price - self.estimated_cost

    @property
    def gross_margin_percent(self):
        if self.estimated_cost is None or self.customer_price <= 0:
            return None
        return ((self.customer_price - self.estimated_cost) / self.customer_price) * 100

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        if not self.valid_until:
            return False
        return self.valid_until < timezone.now().date()

    def __str__(self) -> str:
        return self.reference_code or str(self.id)


class FreightQuoteCharge(UUIDTimestampedModel):
    quote = models.ForeignKey(
        FreightQuote,
        on_delete=models.CASCADE,
        related_name="charges",
    )
    charge_type = models.CharField(
        max_length=40,
        choices=[(kind.value, kind.value) for kind in FreightQuoteChargeType],
        default=FreightQuoteChargeType.OTHER,
    )
    description = models.CharField(max_length=180, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_discount = models.BooleanField(default=False)
    sequence = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["sequence", "created_at"]
        indexes = [
            models.Index(fields=["quote", "sequence"]),
            models.Index(fields=["charge_type"]),
        ]

    def clean(self):
        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({"quantity": "Quantidade não pode ser negativa."})
        if self.unit_amount is not None and self.unit_amount < 0:
            raise ValidationError({"unit_amount": "Valor unitário não pode ser negativo."})
        if self.total_amount is not None and self.total_amount < 0 and not self.is_discount:
            raise ValidationError({"total_amount": "Total não pode ser negativo."})

    def save(self, *args, **kwargs):
        if self.charge_type == FreightQuoteChargeType.DISCOUNT.value:
            self.is_discount = True
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.charge_type} - {self.total_amount}"


class FreightOfferReferenceSequence(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="freight_offer_sequences",
    )
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year"],
                name="unique_freight_offer_sequence_per_org_year",
            )
        ]


class FreightOffer(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_offers",
    )
    freight_request = models.ForeignKey(
        FreightRequest,
        on_delete=models.PROTECT,
        related_name="offers",
    )
    freight_quote = models.ForeignKey(
        FreightQuote,
        on_delete=models.PROTECT,
        related_name="offers",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_freight_offers",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="owned_freight_offers",
        blank=True,
        null=True,
    )
    reference_code = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=30,
        choices=[(status.value, status.value) for status in FreightOfferStatus],
        default=FreightOfferStatus.DRAFT,
    )
    offer_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="BRL", blank=True)
    audience = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in FreightOfferAudience],
        default=FreightOfferAudience.CARRIERS,
    )
    premises_snapshot = models.JSONField(default=dict, blank=True)
    internal_notes = models.TextField(blank=True)
    published_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    ready_at = models.DateTimeField(blank=True, null=True)
    paused_at = models.DateTimeField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_freight_offers",
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["freight_request", "status"]),
            models.Index(fields=["organization", "audience", "status"]),
            models.Index(fields=["expires_at"]),
        ]

    def clean(self):
        if self.offer_amount is not None and self.offer_amount < 0:
            raise ValidationError({"offer_amount": "Valor da oferta não pode ser negativo."})

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        if not self.expires_at:
            return False
        return self.expires_at <= timezone.now()

    @property
    def spread_amount(self):
        if not self.freight_quote_id:
            return None
        return self.freight_quote.customer_price - self.offer_amount

    @property
    def spread_percent(self):
        spread = self.spread_amount
        if spread is None or self.freight_quote.customer_price <= 0:
            return None
        return (spread / self.freight_quote.customer_price) * 100

    def __str__(self) -> str:
        return self.reference_code or str(self.id)


class FreightOfferTarget(UUIDTimestampedModel):
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="targets",
    )
    carrier = models.ForeignKey(
        "carriers.CarrierProfile",
        on_delete=models.CASCADE,
        related_name="freight_offer_targets",
        blank=True,
        null=True,
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="freight_offer_targets",
        blank=True,
        null=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(carrier__isnull=False, driver__isnull=True)
                    | models.Q(carrier__isnull=True, driver__isnull=False)
                ),
                name="freight_offer_target_exactly_one_entity",
            ),
            models.UniqueConstraint(
                fields=["offer", "carrier"],
                condition=models.Q(carrier__isnull=False),
                name="unique_freight_offer_carrier_target",
            ),
            models.UniqueConstraint(
                fields=["offer", "driver"],
                condition=models.Q(driver__isnull=False),
                name="unique_freight_offer_driver_target",
            ),
        ]


class FreightMatchGeneration(UUIDTimestampedModel):
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="match_generations",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_match_generations",
    )
    algorithm_version = models.CharField(max_length=20)
    generation_number = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="generated_freight_match_generations",
        blank=True,
        null=True,
    )
    candidate_count = models.PositiveIntegerField(default=0)
    eligible_count = models.PositiveIntegerField(default=0)
    ineligible_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-generation_number"]
        indexes = [
            models.Index(fields=["offer", "is_current"]),
            models.Index(fields=["organization", "algorithm_version"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["offer", "generation_number"],
                name="unique_freight_match_generation_per_offer",
            ),
            models.UniqueConstraint(
                fields=["offer"],
                condition=models.Q(is_current=True),
                name="unique_current_freight_match_generation_per_offer",
            ),
        ]


class FreightMatchCandidate(UUIDTimestampedModel):
    generation = models.ForeignKey(
        FreightMatchGeneration,
        on_delete=models.CASCADE,
        related_name="candidates",
    )
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="match_candidates",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_match_candidates",
    )
    carrier = models.ForeignKey(
        "carriers.CarrierProfile",
        on_delete=models.CASCADE,
        related_name="match_candidates",
        blank=True,
        null=True,
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="match_candidates",
        blank=True,
        null=True,
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
        related_name="match_candidates",
        blank=True,
        null=True,
    )
    eligibility_status = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in MatchEligibilityStatus],
        default=MatchEligibilityStatus.UNKNOWN,
    )
    eligibility_reasons = models.JSONField(default=list, blank=True)
    distance_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    compliance_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    vehicle_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    cargo_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    temperature_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    availability_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    performance_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    price_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    total_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    rank_position = models.PositiveIntegerField(blank=True, null=True)
    distance_to_pickup_km = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    estimated_deadhead_minutes = models.PositiveIntegerField(blank=True, null=True)
    algorithm_version = models.CharField(max_length=20)
    score_explanation = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField()

    class Meta:
        ordering = ["rank_position", "-total_score"]
        indexes = [
            models.Index(fields=["offer", "eligibility_status"]),
            models.Index(fields=["generation", "rank_position"]),
            models.Index(fields=["organization", "total_score"]),
            models.Index(fields=["algorithm_version"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["generation", "rank_position"],
                condition=models.Q(rank_position__isnull=False),
                name="unique_rank_per_match_generation",
            ),
        ]

    def clean(self):
        current = (
            self.carrier_id is not None,
            self.driver_id is not None,
            self.vehicle_id is not None,
        )
        if current in {(True, False, False), (False, True, True), (True, True, True)}:
            return
        raise ValidationError(
            {"candidate": "Candidato deve ser carrier, driver+vehicle ou carrier+driver+vehicle."}
        )


class FreightOfferInvitation(UUIDTimestampedModel):
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_offer_invitations",
    )
    match_candidate = models.ForeignKey(
        FreightMatchCandidate,
        on_delete=models.SET_NULL,
        related_name="invitations",
        blank=True,
        null=True,
    )
    carrier = models.ForeignKey(
        "carriers.CarrierProfile",
        on_delete=models.CASCADE,
        related_name="freight_offer_invitations",
        blank=True,
        null=True,
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="freight_offer_invitations",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in FreightOfferInvitationStatus],
        default=FreightOfferInvitationStatus.PENDING,
    )
    sent_at = models.DateTimeField(blank=True, null=True)
    viewed_at = models.DateTimeField(blank=True, null=True)
    responded_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    decline_reason = models.CharField(
        max_length=40,
        choices=[(item.value, item.value) for item in InvitationDeclineReason],
        blank=True,
    )
    decline_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_freight_offer_invitations",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_freight_offer_invitations",
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["offer", "status"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["match_candidate", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(carrier__isnull=False, driver__isnull=True)
                    | models.Q(carrier__isnull=True, driver__isnull=False)
                ),
                name="freight_offer_invitation_single_entity",
            ),
        ]


class MarketplaceEvent(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="marketplace_events",
    )
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="marketplace_events",
    )
    event_type = models.CharField(
        max_length=40,
        choices=[(item.value, item.value) for item in MarketplaceEventType],
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="marketplace_events",
        blank=True,
        null=True,
    )
    carrier = models.ForeignKey(
        "carriers.CarrierProfile",
        on_delete=models.SET_NULL,
        related_name="marketplace_events",
        blank=True,
        null=True,
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.SET_NULL,
        related_name="marketplace_events",
        blank=True,
        null=True,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "event_type"]),
            models.Index(fields=["offer", "event_type"]),
            models.Index(fields=["created_at"]),
        ]


class FreightOfferInterest(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_offer_interests",
    )
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="interests",
    )
    invitation = models.ForeignKey(
        FreightOfferInvitation,
        on_delete=models.SET_NULL,
        related_name="interests",
        blank=True,
        null=True,
    )
    match_candidate = models.ForeignKey(
        FreightMatchCandidate,
        on_delete=models.SET_NULL,
        related_name="interests",
        blank=True,
        null=True,
    )
    carrier = models.ForeignKey(
        "carriers.CarrierProfile",
        on_delete=models.CASCADE,
        related_name="freight_offer_interests",
        blank=True,
        null=True,
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.CASCADE,
        related_name="freight_offer_interests",
        blank=True,
        null=True,
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
        related_name="freight_offer_interests",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in FreightOfferInterestStatus],
        default=FreightOfferInterestStatus.ACTIVE,
    )
    expressed_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["offer", "status"]),
            models.Index(fields=["organization", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["offer", "carrier", "driver", "vehicle"],
                condition=models.Q(status="ACTIVE"),
                name="unique_active_interest_per_candidate_combination",
            )
        ]


class FreightOfferSelection(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_offer_selections",
    )
    offer = models.ForeignKey(
        FreightOffer,
        on_delete=models.CASCADE,
        related_name="selections",
    )
    interest = models.ForeignKey(
        FreightOfferInterest,
        on_delete=models.PROTECT,
        related_name="selections",
    )
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="selections_made",
    )
    selected_at = models.DateTimeField()
    status = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in FreightOfferSelectionStatus],
        default=FreightOfferSelectionStatus.PENDING_CONFIRMATION,
    )
    confirmation_expires_at = models.DateTimeField(blank=True, null=True)
    confirmed_at = models.DateTimeField(blank=True, null=True)
    declined_at = models.DateTimeField(blank=True, null=True)
    declined_reason = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in SelectionDeclineReason],
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True)

    # Operational Snapshot Fields
    carrier_snapshot = models.JSONField(blank=True, null=True)
    driver_snapshot = models.JSONField(blank=True, null=True)
    vehicle_snapshot = models.JSONField(blank=True, null=True)
    route_snapshot = models.JSONField(blank=True, null=True)
    cargo_snapshot = models.JSONField(blank=True, null=True)
    premises_snapshot = models.JSONField(blank=True, null=True)
    match_score_snapshot = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    rank_snapshot = models.IntegerField(blank=True, null=True)
    algorithm_version_snapshot = models.CharField(max_length=20, blank=True, null=True)
    route_intent_bonus_snapshot = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["offer", "status"]),
            models.Index(fields=["organization", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["offer"],
                condition=models.Q(status__in=["PENDING_CONFIRMATION", "CONFIRMED"]),
                name="unique_active_selection_per_offer",
            )
        ]

class FreightOperation(UUIDTimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="freight_operations",
    )
    selection = models.OneToOneField(
        "FreightOfferSelection",
        on_delete=models.PROTECT,
        related_name="operation",
    )
    carrier = models.ForeignKey(
        "carriers.CarrierProfile",
        on_delete=models.PROTECT,
        related_name="operations",
    )
    driver = models.ForeignKey(
        "drivers.Driver",
        on_delete=models.PROTECT,
        related_name="operations",
        blank=True,
        null=True,
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="operations",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in OperationStatus],
        default=OperationStatus.ASSIGNED,
    )
    assigned_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    # optional snapshot of origin request
    request_snapshot = models.JSONField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]

class FreightOperationEvent(UUIDTimestampedModel):
    operation = models.ForeignKey(
        FreightOperation,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in OperationEventType],
    )
    previous_status = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in OperationStatus],
        blank=True,
        null=True,
    )
    new_status = models.CharField(
        max_length=30,
        choices=[(item.value, item.value) for item in OperationStatus],
        blank=True,
        null=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='operation_events',
        null=True,
        blank=True,
    )
    origin = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in OperationEventOrigin],
    )
    occurred_at = models.DateTimeField(blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    notes = models.TextField(blank=True)
    client_event_id = models.CharField(max_length=255, blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["operation", "event_type"]),
            models.Index(fields=["operation", "client_event_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "client_event_id"],
                condition=~models.Q(client_event_id__isnull=True),
                name="unique_event_per_operation",
            )
        ]

class ProofOfDelivery(UUIDTimestampedModel):
    operation = models.OneToOneField(
        FreightOperation,
        on_delete=models.PROTECT,
        related_name="pod",
    )
    receiver_name = models.CharField(max_length=120, blank=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    notes = models.TextField(blank=True)
    # signature_image optional, enable only when media storage is configured
    # signature_image = models.ImageField(upload_to="pods/signatures/", blank=True, null=True)



