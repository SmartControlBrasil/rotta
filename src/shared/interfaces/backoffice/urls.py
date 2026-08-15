from django.urls import path

from .views import BackofficeDashboardView, BackofficeLoginView, BackofficeLogoutView

app_name = "backoffice"

urlpatterns = [
    path("", BackofficeDashboardView.as_view(), name="dashboard"),
    path("login/", BackofficeLoginView.as_view(), name="login"),
    path("logout/", BackofficeLogoutView.as_view(), name="logout"),
]
