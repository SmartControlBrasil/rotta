from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "legal_name",
        "trade_name",
        "customer_type",
        "document_number",
        "organization",
        "status",
        "owner",
    )
    list_filter = ("customer_type", "status", "organization", "owner")
    search_fields = ("legal_name", "trade_name", "document_number", "email")
    readonly_fields = ("id", "created_at", "updated_at")
