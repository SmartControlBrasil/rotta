from django.db import migrations

CUSTOMER_PERMISSIONS = [
    ("customers.view", "View customers"),
    ("customers.create", "Create customers"),
    ("customers.update", "Update customers"),
    ("customers.change_status", "Change customer status"),
    ("customers.assign_owner", "Assign customer owner"),
]

ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": [code for code, _name in CUSTOMER_PERMISSIONS],
    "COMPANY_ADMIN": [code for code, _name in CUSTOMER_PERMISSIONS],
    "COMMERCIAL_MANAGER": [code for code, _name in CUSTOMER_PERMISSIONS],
    "SALESPERSON": ["customers.view", "customers.create", "customers.update"],
}


def seed_customer_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    Role = apps.get_model("identity", "Role")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission_by_code = {}
    for code, name in CUSTOMER_PERMISSIONS:
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


def unseed_customer_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    codes = [code for code, _name in CUSTOMER_PERMISSIONS]
    RolePermission.objects.filter(permission__code__in=codes).delete()
    Permission.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0001_initial"),
        ("identity", "0003_seed_initial_rbac"),
    ]

    operations = [
        migrations.RunPython(seed_customer_permissions, unseed_customer_permissions),
    ]
