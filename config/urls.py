from django.contrib import admin
from django.urls import include, path

from src.shared.infrastructure.django.views import health

urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("app/", include("src.shared.interfaces.backoffice.urls")),
    path("api/v1/", include("src.shared.interfaces.api.v1.urls")),
    path("customer/", include("src.shared.interfaces.customer.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("src.shared.interfaces.http.urls")),
]

handler403 = "src.shared.interfaces.backoffice.views.backoffice_permission_denied"
