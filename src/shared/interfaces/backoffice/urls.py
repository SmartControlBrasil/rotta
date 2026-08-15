from django.urls import path

from .views import (
    AuditLogDetailView,
    AuditLogListView,
    BackofficeDashboardView,
    BackofficeLoginView,
    BackofficeLogoutView,
    MembershipDetailView,
    MembershipListView,
    OrganizationDetailView,
    OrganizationListView,
    PermissionListView,
    RoleDetailView,
    RoleListView,
    UserDetailView,
    UserListView,
)

app_name = "backoffice"

urlpatterns = [
    path("", BackofficeDashboardView.as_view(), name="dashboard"),
    path("login/", BackofficeLoginView.as_view(), name="login"),
    path("logout/", BackofficeLogoutView.as_view(), name="logout"),
    path("organizations/", OrganizationListView.as_view(), name="organizations"),
    path("organizations/<uuid:pk>/", OrganizationDetailView.as_view(), name="organization_detail"),
    path("users/", UserListView.as_view(), name="users"),
    path("users/<uuid:pk>/", UserDetailView.as_view(), name="user_detail"),
    path("memberships/", MembershipListView.as_view(), name="memberships"),
    path("memberships/<uuid:pk>/", MembershipDetailView.as_view(), name="membership_detail"),
    path("roles/", RoleListView.as_view(), name="roles"),
    path("roles/<uuid:pk>/", RoleDetailView.as_view(), name="role_detail"),
    path("permissions/", PermissionListView.as_view(), name="permissions"),
    path("audit/", AuditLogListView.as_view(), name="audit"),
    path("audit/<uuid:pk>/", AuditLogDetailView.as_view(), name="audit_detail"),
]
