from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from src.customers.domain.enums import CustomerStatus, CustomerType
from src.shared.domain.validators import normalize_document, validate_cnpj, validate_cpf
from src.shared.infrastructure.django.models import UUIDTimestampedModel


class Customer(UUIDTimestampedModel):
    customer_type = models.CharField(
        max_length=20,
        choices=[(t.value, t.value) for t in CustomerType],
        default=CustomerType.COMPANY,
        blank=True,
    )
    legal_name = models.CharField(max_length=180)
    trade_name = models.CharField(max_length=180, blank=True)
    document_number = models.CharField(max_length=40)
    state_registration = models.CharField(max_length=40, blank=True)
    municipal_registration = models.CharField(max_length=40, blank=True)

    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    mobile_phone = models.CharField(max_length=40, blank=True)

    postal_code = models.CharField(max_length=20, blank=True)
    street = models.CharField(max_length=180, blank=True)
    number = models.CharField(max_length=20, blank=True)
    complement = models.CharField(max_length=180, blank=True)
    district = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=2, default="BR", blank=True)

    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in CustomerStatus],
        default=CustomerStatus.PROSPECT,
        blank=True,
    )

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="customers",
    )
    business_unit = models.ForeignKey(
        "organizations.BusinessUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customers",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_customers",
    )

    class Meta:
        ordering = ["legal_name"]
        indexes = [
            models.Index(fields=["organization", "document_number"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["owner"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document_number"],
                name="unique_customer_document_per_organization",
            )
        ]

    def clean(self):
        super().clean()
        if self.document_number:
            self.document_number = normalize_document(self.document_number)
            if self.customer_type == CustomerType.INDIVIDUAL:
                if not validate_cpf(self.document_number):
                    raise ValidationError({"document_number": "CPF inválido."})
            elif self.customer_type == CustomerType.COMPANY:
                if not validate_cnpj(self.document_number):
                    raise ValidationError({"document_number": "CNPJ inválido."})

    def save(self, *args, **kwargs):
        if self.document_number:
            self.document_number = normalize_document(self.document_number)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.legal_name
