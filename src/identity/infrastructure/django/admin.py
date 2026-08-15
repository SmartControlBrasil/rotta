from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import MembershipRole, Permission, Role, RolePermission, User


@admin.register(User)
class RottaUserAdmin(UserAdmin):
    list_display = ("username", "email", "is_staff", "is_active", "date_joined")
    readonly_fields = ("id", "last_login", "date_joined")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    inlines = [RolePermissionInline]


@admin.register(MembershipRole)
class MembershipRoleAdmin(admin.ModelAdmin):
    list_display = ("membership", "role", "scope")
    list_filter = ("scope", "role")
