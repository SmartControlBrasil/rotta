from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import defaults as default_views
from django.views.generic import DetailView, ListView, TemplateView

from src.audit.infrastructure.django.models import AuditLog
from src.identity.domain.enums import PermissionCode
from src.identity.infrastructure.django.models import Permission, Role

from .authorization import (
    permission_grant_for,
    scoped_membership_queryset,
    scoped_organization_queryset,
    scoped_user_queryset,
    user_has_backoffice_permission,
)

PAGE_SIZE = 25


class BackofficeContextMixin:
    active_menu = "dashboard"
    page_title = "Dashboard"
    breadcrumbs = ()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            active_menu=self.active_menu,
            page_title=self.page_title,
            breadcrumbs=self.get_breadcrumbs(),
        )
        return context

    def get_breadcrumbs(self):
        return self.breadcrumbs


class BackofficePermissionMixin(LoginRequiredMixin):
    login_url = reverse_lazy("backoffice:login")
    permission_code = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.permission_code and not user_has_backoffice_permission(
            request.user, self.permission_code
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def permission_grant(self):
        return permission_grant_for(self.request.user, self.permission_code)


class FilteredListView(BackofficePermissionMixin, BackofficeContextMixin, ListView):
    paginate_by = PAGE_SIZE

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = self.request.GET
        return context


class BackofficeDashboardView(LoginRequiredMixin, BackofficeContextMixin, TemplateView):
    """NexaDash dashboard backed by real Rotta foundation metrics."""

    template_name = "backoffice/dashboard.html"
    login_url = reverse_lazy("backoffice:login")
    active_menu = "dashboard"
    page_title = "Dashboard"
    breadcrumbs = (("Dashboard", None),)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        metrics = []

        if user_has_backoffice_permission(user, PermissionCode.ORGANIZATIONS_VIEW):
            metrics.append(
                {
                    "label": "Organizations",
                    "value": scoped_organization_queryset(
                        user, PermissionCode.ORGANIZATIONS_VIEW
                    ).count(),
                    "url": reverse_lazy("backoffice:organizations"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.USERS_VIEW):
            metrics.append(
                {
                    "label": "Users",
                    "value": scoped_user_queryset(user, PermissionCode.USERS_VIEW).count(),
                    "url": reverse_lazy("backoffice:users"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.MEMBERSHIPS_VIEW):
            metrics.append(
                {
                    "label": "Memberships",
                    "value": scoped_membership_queryset(
                        user, PermissionCode.MEMBERSHIPS_VIEW
                    ).count(),
                    "url": reverse_lazy("backoffice:memberships"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.ROLES_MANAGE):
            metrics.append(
                {
                    "label": "Roles",
                    "value": Role.objects.count(),
                    "url": reverse_lazy("backoffice:roles"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.AUDIT_VIEW):
            metrics.append(
                {
                    "label": "Audit logs",
                    "value": AuditLog.objects.count(),
                    "url": reverse_lazy("backoffice:audit"),
                }
            )

        audit_since = timezone.now() - timedelta(days=7)
        audit_by_day = []
        if user_has_backoffice_permission(user, PermissionCode.AUDIT_VIEW):
            audit_by_day = list(
                AuditLog.objects.filter(created_at__gte=audit_since)
                .extra(select={"day": "date(created_at)"})
                .values("day")
                .annotate(total=Count("id"))
                .order_by("day")
            )

        context["metrics"] = metrics
        context["recent_audit_logs"] = AuditLog.objects.select_related(
            "actor", "organization"
        )[:8] if user_has_backoffice_permission(user, PermissionCode.AUDIT_VIEW) else []
        context["audit_by_day"] = audit_by_day
        return context


class OrganizationListView(FilteredListView):
    template_name = "backoffice/pages/organizations/list.html"
    context_object_name = "organizations"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Organizations"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Organizations", None))

    def get_queryset(self):
        queryset = scoped_organization_queryset(
            self.request.user, self.permission_code
        ).prefetch_related("business_units", "branches", "departments", "teams")
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if query:
            queryset = queryset.filter(name__icontains=query)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset


class OrganizationDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/organizations/detail.html"
    context_object_name = "organization"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Organization"

    def get_queryset(self):
        queryset = scoped_organization_queryset(self.request.user, self.permission_code)
        return queryset.prefetch_related(
            "business_units",
            "branches__business_unit",
            "departments__branch",
            "teams__department",
            "memberships__user",
            "memberships__membership_roles__role",
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            (self.object.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_view_memberships"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.MEMBERSHIPS_VIEW
        )
        return context


class UserListView(FilteredListView):
    template_name = "backoffice/pages/users/list.html"
    context_object_name = "users"
    permission_code = PermissionCode.USERS_VIEW
    active_menu = "users"
    page_title = "Users"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Users", None))

    def get_queryset(self):
        queryset = scoped_user_queryset(self.request.user, self.permission_code).prefetch_related(
            "memberships__organization"
        )
        email = self.request.GET.get("email", "").strip()
        active = self.request.GET.get("active", "").strip()
        if email:
            queryset = queryset.filter(email__icontains=email)
        if active == "yes":
            queryset = queryset.filter(is_active=True)
        elif active == "no":
            queryset = queryset.filter(is_active=False)
        return queryset.order_by("username")


class UserDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/users/detail.html"
    context_object_name = "account"
    permission_code = PermissionCode.USERS_VIEW
    active_menu = "users"
    page_title = "User"

    def get_queryset(self):
        return scoped_user_queryset(self.request.user, self.permission_code).prefetch_related(
            "memberships__organization", "memberships__membership_roles__role"
        )

    def get_breadcrumbs(self):
        label = self.object.email or self.object.username
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Users", reverse_lazy("backoffice:users")),
            (label, None),
        )


class MembershipListView(FilteredListView):
    template_name = "backoffice/pages/memberships/list.html"
    context_object_name = "memberships"
    permission_code = PermissionCode.MEMBERSHIPS_VIEW
    active_menu = "memberships"
    page_title = "Memberships"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Memberships", None))

    def get_queryset(self):
        queryset = scoped_membership_queryset(self.request.user, self.permission_code)
        queryset = queryset.select_related(
            "user", "organization", "business_unit", "branch", "department", "team"
        ).prefetch_related("membership_roles__role")
        organization = self.request.GET.get("organization", "").strip()
        user = self.request.GET.get("user", "").strip()
        role = self.request.GET.get("role", "").strip()
        if organization:
            queryset = queryset.filter(organization__name__icontains=organization)
        if user:
            queryset = queryset.filter(user__username__icontains=user)
        if role:
            queryset = queryset.filter(membership_roles__role__code__icontains=role)
        return queryset.distinct()


class MembershipDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/memberships/detail.html"
    context_object_name = "membership"
    permission_code = PermissionCode.MEMBERSHIPS_VIEW
    active_menu = "memberships"
    page_title = "Membership"

    def get_queryset(self):
        return scoped_membership_queryset(self.request.user, self.permission_code).select_related(
            "user", "organization", "business_unit", "branch", "department", "team"
        ).prefetch_related("membership_roles__role__permissions")

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Memberships", reverse_lazy("backoffice:memberships")),
            (str(self.object), None),
        )


class RoleListView(FilteredListView):
    model = Role
    template_name = "backoffice/pages/roles/list.html"
    context_object_name = "roles"
    permission_code = PermissionCode.ROLES_MANAGE
    active_menu = "roles"
    page_title = "Roles"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Roles", None))

    def get_queryset(self):
        return Role.objects.prefetch_related("permissions")


class RoleDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    model = Role
    template_name = "backoffice/pages/roles/detail.html"
    context_object_name = "role"
    permission_code = PermissionCode.ROLES_MANAGE
    active_menu = "roles"
    page_title = "Role"

    def get_queryset(self):
        return Role.objects.prefetch_related("role_permissions__permission")

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Roles", reverse_lazy("backoffice:roles")),
            (self.object.code, None),
        )


class PermissionListView(FilteredListView):
    model = Permission
    template_name = "backoffice/pages/permissions/list.html"
    context_object_name = "permissions"
    permission_code = PermissionCode.ROLES_MANAGE
    active_menu = "permissions"
    page_title = "Permissions"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Permissions", None))
    paginate_by = None

    def get_queryset(self):
        return Permission.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grouped = {}
        for permission in context["permissions"]:
            prefix = permission.code.split(".", 1)[0]
            grouped.setdefault(prefix, []).append(permission)
        context["grouped_permissions"] = grouped
        return context


class AuditLogListView(FilteredListView):
    template_name = "backoffice/pages/audit/list.html"
    context_object_name = "audit_logs"
    permission_code = PermissionCode.AUDIT_VIEW
    active_menu = "audit"
    page_title = "AuditLog"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Audit", None))

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor", "organization")
        grant = self.permission_grant()
        if not self.request.user.is_superuser and grant.scope.name != "ALL":
            organization_ids = [membership.organization_id for membership in grant.memberships]
            queryset = queryset.filter(organization_id__in=organization_ids)
        action = self.request.GET.get("action", "").strip()
        actor = self.request.GET.get("actor", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        start = parse_date(self.request.GET.get("start", ""))
        end = parse_date(self.request.GET.get("end", ""))
        if action:
            queryset = queryset.filter(action__icontains=action)
        if actor:
            queryset = queryset.filter(actor__username__icontains=actor)
        if organization:
            queryset = queryset.filter(organization__name__icontains=organization)
        if start:
            queryset = queryset.filter(created_at__date__gte=start)
        if end:
            queryset = queryset.filter(created_at__date__lte=end)
        return queryset


class AuditLogDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/audit/detail.html"
    context_object_name = "audit_log"
    permission_code = PermissionCode.AUDIT_VIEW
    active_menu = "audit"
    page_title = "AuditLog"

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor", "organization")
        grant = self.permission_grant()
        if not self.request.user.is_superuser and grant.scope.name != "ALL":
            organization_ids = [membership.organization_id for membership in grant.memberships]
            queryset = queryset.filter(organization_id__in=organization_ids)
        return queryset

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Audit", reverse_lazy("backoffice:audit")),
            (self.object.action, None),
        )


class BackofficeLoginView(LoginView):
    """Session login using Rotta's configured AUTH_USER_MODEL."""

    template_name = "backoffice/pages/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy("backoffice:dashboard")


class BackofficeLogoutView(LogoutView):
    next_page = reverse_lazy("backoffice:login")


class BackofficeForbiddenView(LoginRequiredMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/403.html"
    active_menu = ""
    page_title = "Acesso negado"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Acesso negado", None))


def backoffice_permission_denied(request, exception=None):
    if request.path.startswith("/app/"):
        return render(
            request,
            "backoffice/pages/403.html",
            {
                "active_menu": "",
                "page_title": "Acesso negado",
                "breadcrumbs": (
                    ("Dashboard", reverse_lazy("backoffice:dashboard")),
                    ("Acesso negado", None),
                ),
            },
            status=403,
        )
    return default_views.permission_denied(request, exception)
