from django.contrib import admin

from .models import CarrierDriverLink, CarrierProfile, CarrierVehicleLink


@admin.register(CarrierProfile)
class CarrierProfileAdmin(admin.ModelAdmin):
    list_display = (
        "trade_name",
        "organization",
        "tenant",
        "status",
        "cargo_profile",
        "owner",
    )
    list_filter = ("status", "cargo_profile", "tenant", "owner")
    search_fields = ("trade_name", "rntrc", "email")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CarrierDriverLink)
class CarrierDriverLinkAdmin(admin.ModelAdmin):
    list_display = ("carrier", "driver", "active")
    list_filter = ("active",)
    search_fields = ("carrier__trade_name", "driver__full_name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CarrierVehicleLink)
class CarrierVehicleLinkAdmin(admin.ModelAdmin):
    list_display = ("carrier", "vehicle", "link_type", "active")
    list_filter = ("active", "link_type")
    search_fields = ("carrier__trade_name", "vehicle__plate")
    readonly_fields = ("id", "created_at", "updated_at")
