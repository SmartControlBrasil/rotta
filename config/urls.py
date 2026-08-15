from django.contrib import admin
from django.urls import include, path

from src.shared.infrastructure.django.views import health

urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("src.shared.interfaces.http.urls")),
]
