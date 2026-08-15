from django.contrib import admin

from .models import DriverVehicleAssignment, RefrigerationProfile, Vehicle, VehicleDocument


class DriverVehicleAssignmentInline(admin.TabularInline):
    model = DriverVehicleAssignment
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "plate",
        "vehicle_type",
        "cargo_profile",
        "organization",
        "status",
        "operational_status",
    )
    list_filter = (
        "vehicle_type",
        "body_type",
        "cargo_profile",
        "status",
        "operational_status",
        "ownership_type",
        "organization",
    )
    search_fields = ("plate", "renavam", "chassis", "brand", "model", "organization__name")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [DriverVehicleAssignmentInline]


@admin.register(DriverVehicleAssignment)
class DriverVehicleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("driver", "vehicle", "active", "primary", "valid_from", "valid_until")
    list_filter = ("active", "primary")
    search_fields = ("driver__full_name", "vehicle__plate")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(RefrigerationProfile)
class RefrigerationProfileAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle",
        "control_type",
        "temperature_min_c",
        "temperature_max_c",
        "next_maintenance_date",
    )
    list_filter = ("control_type", "has_refrigeration_unit")
    search_fields = ("vehicle__plate", "unit_manufacturer", "unit_model")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(VehicleDocument)
class VehicleDocumentAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "document_type", "status", "expiration_date", "reviewed_at")
    list_filter = ("document_type", "status")
    search_fields = ("vehicle__plate", "storage_key")
    readonly_fields = ("id", "created_at", "updated_at")
