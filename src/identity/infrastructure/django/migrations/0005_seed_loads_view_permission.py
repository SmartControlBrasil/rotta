from django.db import migrations

LOADS_PERMISSIONS = [
    ("loads.view", "View loads"),
]

ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": ["loads.view"],
    "COMPANY_ADMIN": ["loads.view"],
    "OPERATIONS_MANAGER": ["loads.view"],
    "DISPATCHER": ["loads.view"],
}


def seed_loads_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    Role = apps.get_model("identity", "Role")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission_by_code = {}
    for code, name in LOADS_PERMISSIONS:
        permission, _created = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name},
        )
        permission_by_code[code] = permission

    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        try:
            role = Role.objects.get(code=role_code)
            for permission_code in permission_codes:
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=permission_by_code[permission_code],
                )
        except Role.DoesNotExist:
            pass


def unseed_loads_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    codes = [code for code, _name in LOADS_PERMISSIONS]
    RolePermission.objects.filter(permission__code__in=codes).delete()
    Permission.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0004_seed_freight_operations_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_loads_permissions, unseed_loads_permissions),
    ]
