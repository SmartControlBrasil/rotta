from django.conf import settings
from django.db import models

from src.organizations.domain.enums import MembershipStatus, OrganizationType
from src.shared.infrastructure.django.models import UUIDTimestampedModel


class Organization(UUIDTimestampedModel):
    name = models.CharField(max_length=180)
    legal_name = models.CharField(max_length=220, blank=True)
    document = models.CharField(max_length=40, blank=True)
    type = models.CharField(
        max_length=40,
        choices=[(kind.value, kind.value) for kind in OrganizationType],
        default=OrganizationType.TRANSPORT_COMPANY,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["document"],
                condition=~models.Q(document=""),
                name="unique_organization_document_when_present",
            )
        ]

    def __str__(self) -> str:
        return self.name


class BusinessUnit(UUIDTimestampedModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="business_units",
    )
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_business_unit_name_per_organization",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Branch(UUIDTimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="branches"
    )
    business_unit = models.ForeignKey(
        BusinessUnit,
        on_delete=models.SET_NULL,
        related_name="branches",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=~models.Q(code=""),
                name="unique_branch_code_per_organization_when_present",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Department(UUIDTimestampedModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="departments",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="departments",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_department_name_per_organization",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Team(UUIDTimestampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name="teams",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_team_name_per_organization",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Membership(UUIDTimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    business_unit = models.ForeignKey(
        BusinessUnit,
        on_delete=models.SET_NULL,
        related_name="memberships",
        blank=True,
        null=True,
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        related_name="memberships",
        blank=True,
        null=True,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name="memberships",
        blank=True,
        null=True,
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name="memberships",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in MembershipStatus],
        default=MembershipStatus.ACTIVE,
    )
    roles = models.ManyToManyField(
        "identity.Role",
        through="identity.MembershipRole",
        related_name="memberships",
        blank=True,
    )

    class Meta:
        ordering = ["organization__name", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="unique_user_membership_per_organization",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization}"
