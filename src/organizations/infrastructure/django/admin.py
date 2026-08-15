from django.contrib import admin

from .models import Branch, BusinessUnit, Department, Membership, Organization, Team


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "document", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name", "legal_name", "document")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(BusinessUnit)
class BusinessUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active")
    list_filter = ("is_active",)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "business_unit", "code", "is_active")
    list_filter = ("is_active",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "branch", "is_active")
    list_filter = ("is_active",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "department", "is_active")
    list_filter = ("is_active",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "business_unit",
        "branch",
        "department",
        "team",
        "status",
    )
    list_filter = ("status", "organization")
    readonly_fields = ("id", "created_at", "updated_at")
