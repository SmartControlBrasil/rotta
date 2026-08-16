from django.db import migrations

SETTINGS_PERMISSIONS = [
    ("settings.view", "View settings"),
    ("settings.update", "Update settings"),
]

ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": ["settings.view", "settings.update"],
    "COMPANY_ADMIN": ["settings.view", "settings.update"],
    "OPERATIONS_MANAGER": ["settings.view"],
    "DISPATCHER": ["settings.view"],
    "FINANCIAL_MANAGER": ["settings.view"],
    "FINANCIAL_ANALYST": ["settings.view"],
    "COMMERCIAL_MANAGER": ["settings.view"],
    "SALESPERSON": ["settings.view"],
    "AUDITOR": ["settings.view"],
    "VIEWER": ["settings.view"],
}


def seed_settings_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    Role = apps.get_model("identity", "Role")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission_by_code = {}
    for code, name in SETTINGS_PERMISSIONS:
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


def unseed_settings_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    codes = [code for code, _name in SETTINGS_PERMISSIONS]
    RolePermission.objects.filter(permission__code__in=codes).delete()
    Permission.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0007_seed_reports_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_settings_permissions, unseed_settings_permissions),
    ]
