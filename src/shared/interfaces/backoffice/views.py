from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.views.generic import TemplateView


class BackofficeDashboardView(LoginRequiredMixin, TemplateView):
    """NexaDash visual adapter for the Rotta operational backoffice."""

    template_name = "backoffice/dashboard.html"
    login_url = reverse_lazy("backoffice:login")


class BackofficeLoginView(LoginView):
    """Session login using Rotta's configured AUTH_USER_MODEL."""

    template_name = "backoffice/pages/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy("backoffice:dashboard")


class BackofficeLogoutView(LogoutView):
    next_page = reverse_lazy("backoffice:login")
