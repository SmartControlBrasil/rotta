from django.contrib import admin
from django.views.generic import RedirectView
from django.urls import include, path

from src.shared.infrastructure.django.views import health
from src.shared.interfaces.backoffice.views import (
    RoleBasedAccountsLoginView,
    RoleBasedLoginRedirectView,
)

urlpatterns = [
    path(
        "favicon.ico",
        RedirectView.as_view(
            url="/static/backoffice/nexadash/images/favicon.ico",
            permanent=True,
        ),
        name="favicon",
    ),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("app/", include("src.shared.interfaces.backoffice.urls")),
    path("api/v1/", include("src.shared.interfaces.api.v1.urls")),
    path("customer/", include("src.shared.interfaces.customer.urls")),
    path("accounts/login/", RoleBasedAccountsLoginView.as_view(), name="login"),
    path("accounts/redirect/", RoleBasedLoginRedirectView.as_view(), name="account_redirect"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("src.shared.interfaces.http.urls")),
]

handler403 = "src.shared.interfaces.backoffice.views.backoffice_permission_denied"
