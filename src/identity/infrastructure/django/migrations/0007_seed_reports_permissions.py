from django.db import migrations

REPORTS_PERMISSIONS = [
    ("reports.view", "View reports"),
]

ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": ["reports.view"],
    "COMPANY_ADMIN": ["reports.view"],
    "OPERATIONS_MANAGER": ["reports.view"],
    "DISPATCHER": ["reports.view"],
    "FINANCIAL_MANAGER": ["reports.view"],
    "FINANCIAL_ANALYST": ["reports.view"],
    "COMMERCIAL_MANAGER": ["reports.view"],
    "SALESPERSON": ["reports.view"],
    "AUDITOR": ["reports.view"],
    "VIEWER": ["reports.view"],
}


def seed_reports_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    Role = apps.get_model("identity", "Role")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission_by_code = {}
    for code, name in REPORTS_PERMISSIONS:
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


def unseed_reports_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    codes = [code for code, _name in REPORTS_PERMISSIONS]
    RolePermission.objects.filter(permission__code__in=codes).delete()
    Permission.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0006_seed_tracking_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_reports_permissions, unseed_reports_permissions),
    ]
