from django.contrib import admin

from .models import Driver, DriverDocument


class DriverDocumentInline(admin.TabularInline):
    model = DriverDocument
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at", "reviewed_at")


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "organization",
        "status",
        "approval_status",
        "availability_status",
    )
    list_filter = ("status", "approval_status", "availability_status", "organization")
    search_fields = ("full_name", "phone", "document", "driver_license_number")
    readonly_fields = ("id", "created_at", "updated_at", "approved_at")
    inlines = [DriverDocumentInline]


@admin.register(DriverDocument)
class DriverDocumentAdmin(admin.ModelAdmin):
    list_display = ("driver", "document_type", "status", "expiration_date", "reviewed_at")
    list_filter = ("document_type", "status")
    search_fields = ("driver__full_name", "storage_key")
    readonly_fields = ("id", "created_at", "updated_at", "reviewed_at")
