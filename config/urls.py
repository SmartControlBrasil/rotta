from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from src.shared.infrastructure.django.views import health

urlpatterns = [
    path("", TemplateView.as_view(template_name="temporary/home.html"), name="home"),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
]
