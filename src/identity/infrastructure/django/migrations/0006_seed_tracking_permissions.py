from django.db import migrations

TRACKING_PERMISSIONS = [
    ("tracking.view", "View tracking"),
    ("tracking.start", "Start tracking session"),
    ("tracking.record", "Record location points"),
    ("tracking.end", "End tracking session"),
]

ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": [code for code, _name in TRACKING_PERMISSIONS],
    "COMPANY_ADMIN": [code for code, _name in TRACKING_PERMISSIONS],
    "OPERATIONS_MANAGER": [code for code, _name in TRACKING_PERMISSIONS],
    "DISPATCHER": ["tracking.view"],
}


def seed_tracking_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    Role = apps.get_model("identity", "Role")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission_by_code = {}
    for code, name in TRACKING_PERMISSIONS:
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


def unseed_tracking_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    codes = [code for code, _name in TRACKING_PERMISSIONS]
    RolePermission.objects.filter(permission__code__in=codes).delete()
    Permission.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0005_seed_loads_view_permission"),
    ]

    operations = [
        migrations.RunPython(seed_tracking_permissions, unseed_tracking_permissions),
    ]
