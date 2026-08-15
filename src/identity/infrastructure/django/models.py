from django.contrib.auth.models import AbstractUser
from django.db import models

from src.shared.domain.enums import AccessScope
from src.shared.infrastructure.django.models import UUIDPrimaryKeyModel, UUIDTimestampedModel


class User(AbstractUser, UUIDPrimaryKeyModel):
    email = models.EmailField(blank=False)

    class Meta:
        indexes = [models.Index(fields=["email"])]


class Permission(UUIDTimestampedModel):
    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Role(UUIDTimestampedModel):
    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    permissions = models.ManyToManyField(
        Permission,
        through="RolePermission",
        related_name="roles",
        blank=True,
    )

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class RolePermission(UUIDTimestampedModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"],
                name="unique_role_permission",
            )
        ]


class MembershipRole(UUIDTimestampedModel):
    membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.CASCADE,
        related_name="membership_roles",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="membership_roles")
    scope = models.CharField(
        max_length=20,
        choices=[(scope.value, scope.value) for scope in AccessScope],
        default=AccessScope.COMPANY,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "role"],
                name="unique_membership_role",
            )
        ]

    def __str__(self) -> str:
        return f"{self.membership_id}:{self.role.code}"
