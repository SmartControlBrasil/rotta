from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "organization", "target_type", "target_id")
    list_filter = ("action", "created_at")
    search_fields = ("action", "target_type", "target_id", "request_id")
    readonly_fields = (
        "id",
        "actor",
        "organization",
        "action",
        "target_type",
        "target_id",
        "before",
        "after",
        "metadata",
        "ip_address",
        "user_agent",
        "request_id",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
