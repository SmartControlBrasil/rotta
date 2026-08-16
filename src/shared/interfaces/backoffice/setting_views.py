from django.views.generic import TemplateView
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.conf import settings

from src.identity.domain.enums import PermissionCode
from src.identity.infrastructure.django.models import Role, Permission
from src.organizations.infrastructure.django.models import (
    Organization,
    BusinessUnit,
    Branch,
    Department,
    Team,
    Membership,
)
from src.organizations.application.services import update_organization
from src.shared.interfaces.backoffice.views import (
    BackofficePermissionMixin,
    BackofficeContextMixin,
    OrganizationForm,
)
from src.shared.interfaces.backoffice.authorization import (
    scoped_organization_queryset,
    scoped_business_unit_queryset,
    scoped_branch_queryset,
    scoped_department_queryset,
    scoped_team_queryset,
    scoped_membership_queryset,
    scoped_user_queryset,
    user_has_backoffice_permission,
    permission_grant_for,
)

class SettingOverviewView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/overview.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Configurações - Visão Geral"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", None),
            ("Visão Geral", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "overview"
        user = self.request.user
        context["orgs_count"] = scoped_organization_queryset(user, PermissionCode.SETTINGS_VIEW).count()
        context["units_count"] = scoped_business_unit_queryset(user, PermissionCode.ORGANIZATIONS_VIEW).count()
        context["users_count"] = scoped_user_queryset(user, PermissionCode.USERS_VIEW).count()
        context["roles_count"] = Role.objects.count()
        return context

class SettingOrganizationView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/organization.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Configurações da Organização"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Organização", None),
        )

    def get_object(self):
        orgs = scoped_organization_queryset(self.request.user, PermissionCode.SETTINGS_VIEW)
        org_id = self.request.GET.get("org_id")
        if org_id:
            return get_object_or_404(orgs, pk=org_id)
        first_org = orgs.first()
        if not first_org:
            raise PermissionDenied("Nenhuma organização associada.")
        return first_org

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "organization"
        org = self.get_object()
        context["organization"] = org
        
        update_orgs = scoped_organization_queryset(self.request.user, PermissionCode.SETTINGS_UPDATE)
        can_edit = org in update_orgs
        context["can_edit"] = can_edit
        
        if "form" not in context:
            context["form"] = OrganizationForm(instance=org)
            if not can_edit:
                for field in context["form"].fields.values():
                    field.disabled = True
                    
        return context

    def post(self, request, *args, **kwargs):
        org = self.get_object()
        update_orgs = scoped_organization_queryset(self.request.user, PermissionCode.SETTINGS_UPDATE)
        if org not in update_orgs:
            raise PermissionDenied("Sem permissão para atualizar esta organização.")
            
        form = OrganizationForm(request.POST, instance=org)
        if form.is_valid():
            try:
                update_organization(
                    org,
                    name=form.cleaned_data["name"],
                    legal_name=form.cleaned_data["legal_name"],
                    document=form.cleaned_data["document"],
                    type=form.cleaned_data["type"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                messages.success(request, "Configurações da organização salvas com sucesso.")
                return redirect(f"{reverse('backoffice:setting_organization')}?org_id={org.id}")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))

class SettingStructureView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/structure.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Estrutura Organizacional"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Estrutura Organizacional", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "structure"
        user = self.request.user
        context["units_count"] = scoped_business_unit_queryset(user, PermissionCode.ORGANIZATIONS_VIEW).count()
        context["branches_count"] = scoped_branch_queryset(user, PermissionCode.ORGANIZATIONS_VIEW).count()
        context["departments_count"] = scoped_department_queryset(user, PermissionCode.ORGANIZATIONS_VIEW).count()
        context["teams_count"] = scoped_team_queryset(user, PermissionCode.ORGANIZATIONS_VIEW).count()
        context["memberships_count"] = scoped_membership_queryset(user, PermissionCode.MEMBERSHIPS_VIEW).count()
        return context

class SettingAccessView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/access.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Usuários e Acessos"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Usuários e Acessos", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "access"
        user = self.request.user
        context["users_count"] = scoped_user_queryset(user, PermissionCode.USERS_VIEW).count()
        context["roles_count"] = Role.objects.count()
        context["permissions_count"] = Permission.objects.count()
        context["memberships_count"] = scoped_membership_queryset(user, PermissionCode.MEMBERSHIPS_VIEW).count()
        return context

class SettingOperationView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/operation.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Configurações Operacionais"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Operação", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "operation"
        context["max_delay_tolerance_minutes"] = 15
        context["matching_radius_km"] = 50
        context["cancel_deadline_hours"] = 2
        return context

class SettingMarketplaceView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/marketplace.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Configurações Comerciais e Marketplace"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Fretes e Marketplace", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "marketplace"
        context["commission_percentage"] = 5.0
        context["free_tier_vehicle_limit"] = 3
        return context

class SettingThermalView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/thermal.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Configuração Térmica"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Carga Refrigerada", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "thermal"
        context["stale_threshold_minutes"] = 15
        context["excursion_validation_readings"] = 3
        return context

class SettingNotificationsView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/notifications.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Central de Notificações"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Notificações", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "notifications"
        return context

class SettingIntegrationsView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/integrations.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "API e Integrações"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Integrações e API", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "integrations"
        context["api_v1_status"] = "ACTIVE"
        context["masked_api_key"] = "rot_live_••••••••••••••••••••3a9c"
        return context

class SettingSecurityView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/settings/security.html"
    permission_code = PermissionCode.SETTINGS_VIEW
    active_menu = "settings"
    page_title = "Configurações de Segurança e Acessos"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Configurações", reverse_lazy("backoffice:setting_overview")),
            ("Segurança", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["setting_key"] = "security"
        context["session_timeout_seconds"] = 3600
        context["mfa_policy"] = "OPTIONAL"
        return context
