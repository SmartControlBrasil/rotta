from dataclasses import dataclass

from django.db import transaction

from src.identity.domain.rbac import PERMISSIONS, ROLE_PERMISSIONS, ROLES

from .models import Permission, Role, RolePermission


@dataclass(frozen=True)
class BootstrapStats:
    permissions_created: int = 0
    permissions_updated: int = 0
    permissions_unchanged: int = 0
    roles_created: int = 0
    roles_updated: int = 0
    roles_unchanged: int = 0
    role_permissions_created: int = 0
    role_permissions_unchanged: int = 0


@transaction.atomic
def sync_rbac() -> BootstrapStats:
    stats = {
        "permissions_created": 0,
        "permissions_updated": 0,
        "permissions_unchanged": 0,
        "roles_created": 0,
        "roles_updated": 0,
        "roles_unchanged": 0,
        "role_permissions_created": 0,
        "role_permissions_unchanged": 0,
    }

    permission_by_code: dict[str, Permission] = {}
    for definition in PERMISSIONS:
        defaults = {"name": definition.name, "description": definition.description}
        permission, created = Permission.objects.get_or_create(
            code=definition.code.value,
            defaults=defaults,
        )
        if created:
            stats["permissions_created"] += 1
        else:
            changed = any(getattr(permission, field) != value for field, value in defaults.items())
            if changed:
                for field, value in defaults.items():
                    setattr(permission, field, value)
                permission.save(update_fields=[*defaults.keys(), "updated_at"])
                stats["permissions_updated"] += 1
            else:
                stats["permissions_unchanged"] += 1
        permission_by_code[definition.code.value] = permission

    role_by_code: dict[str, Role] = {}
    for definition in ROLES:
        defaults = {"name": definition.name, "description": definition.description}
        role, created = Role.objects.get_or_create(code=definition.code.value, defaults=defaults)
        if created:
            stats["roles_created"] += 1
        else:
            changed = any(getattr(role, field) != value for field, value in defaults.items())
            if changed:
                for field, value in defaults.items():
                    setattr(role, field, value)
                role.save(update_fields=[*defaults.keys(), "updated_at"])
                stats["roles_updated"] += 1
            else:
                stats["roles_unchanged"] += 1
        role_by_code[definition.code.value] = role

    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        role = role_by_code[role_code.value]
        for permission_code in permission_codes:
            _binding, created = RolePermission.objects.get_or_create(
                role=role,
                permission=permission_by_code[permission_code.value],
            )
            if created:
                stats["role_permissions_created"] += 1
            else:
                stats["role_permissions_unchanged"] += 1

    return BootstrapStats(**stats)
