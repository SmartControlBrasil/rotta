from django.contrib import admin

from .models import (
    FreightQuote,
    FreightQuoteCharge,
    FreightRequest,
    FreightRequestCargo,
    FreightRequestStop,
)


class FreightRequestStopInline(admin.TabularInline):
    model = FreightRequestStop
    extra = 0


class FreightRequestCargoInline(admin.StackedInline):
    model = FreightRequestCargo
    extra = 0


@admin.register(FreightRequest)
class FreightRequestAdmin(admin.ModelAdmin):
    list_display = ("reference_code", "customer", "organization", "status", "owner", "created_at")
    list_filter = ("status", "priority", "organization")
    search_fields = ("reference_code", "customer__legal_name")
    readonly_fields = ("id", "created_at", "updated_at", "submitted_at", "cancelled_at")
    inlines = [FreightRequestStopInline, FreightRequestCargoInline]


class FreightQuoteChargeInline(admin.TabularInline):
    model = FreightQuoteCharge
    extra = 0


@admin.register(FreightQuote)
class FreightQuoteAdmin(admin.ModelAdmin):
    list_display = (
        "reference_code",
        "version",
        "freight_request",
        "status",
        "total_amount",
        "valid_until",
    )
    list_filter = ("status", "organization")
    inlines = [FreightQuoteChargeInline]
