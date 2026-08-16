from django.db import migrations

FREIGHT_OPERATIONS_PERMISSIONS = [
    ("freight_operations.view", "View freight operations"),
    ("freight_operations.create", "Create freight operations"),
    ("freight_operations.change_status", "Change freight operation status"),
    ("freight_operations.report_incident", "Report incident on freight operation"),
    ("freight_operations.cancel", "Cancel freight operation"),
    ("freight_operations.record_pod", "Record proof of delivery for freight operation"),
]

ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": [code for code, _name in FREIGHT_OPERATIONS_PERMISSIONS],
    "OPERATIONS_MANAGER": [code for code, _name in FREIGHT_OPERATIONS_PERMISSIONS],
    "DISPATCHER": [
        "freight_operations.view",
        "freight_operations.change_status",
        "freight_operations.report_incident",
        "freight_operations.cancel",
        "freight_operations.record_pod",
    ],
}


def seed_freight_operations_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    Role = apps.get_model("identity", "Role")
    RolePermission = apps.get_model("identity", "RolePermission")

    permission_by_code = {}
    for code, name in FREIGHT_OPERATIONS_PERMISSIONS:
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


def unseed_freight_operations_permissions(apps, schema_editor):
    Permission = apps.get_model("identity", "Permission")
    RolePermission = apps.get_model("identity", "RolePermission")

    codes = [code for code, _name in FREIGHT_OPERATIONS_PERMISSIONS]
    RolePermission.objects.filter(permission__code__in=codes).delete()
    Permission.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0003_seed_initial_rbac"),
    ]

    operations = [
        migrations.RunPython(seed_freight_operations_permissions, unseed_freight_operations_permissions),
    ]
