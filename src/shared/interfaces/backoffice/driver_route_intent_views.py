from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import models as django_models
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import DetailView, TemplateView, View

from src.audit.infrastructure.django.models import AuditLog
from src.drivers.application.route_intent_services import (
    DriverRouteIntentData,
    activate_driver_route_intent,
    apply_route_intent_expiration_if_needed,
    cancel_driver_route_intent,
    create_driver_route_intent,
    update_driver_route_intent,
)
from src.drivers.domain.route_intent_enums import (
    DriverRouteIntentSource,
    DriverRouteIntentStatus,
    DriverRouteIntentType,
    RouteIntentCargoPreference,
)
from src.drivers.infrastructure.django.models import Driver, DriverRouteIntent
from src.identity.domain.enums import PermissionCode
from src.vehicles.infrastructure.django.models import Vehicle

from .authorization import (
    scoped_driver_queryset,
    scoped_driver_route_intent_queryset,
    scoped_vehicle_queryset,
    user_has_backoffice_permission,
)
from .views import BackofficeContextMixin, BackofficePermissionMixin, FilteredListView

INTENT_TYPE_LABELS = {
    DriverRouteIntentType.RETURN_LOAD.value: "Retorno",
    DriverRouteIntentType.DESTINATION_PREFERENCE.value: "Destino desejado",
}

STATUS_LABELS = {
    DriverRouteIntentStatus.DRAFT.value: "Rascunho",
    DriverRouteIntentStatus.ACTIVE.value: "Ativa",
    DriverRouteIntentStatus.EXPIRED.value: "Expirada",
    DriverRouteIntentStatus.CANCELLED.value: "Cancelada",
    DriverRouteIntentStatus.COMPLETED.value: "Concluída",
}

CARGO_PREFERENCE_LABELS = {
    RouteIntentCargoPreference.DRY_CARGO.value: "Carga seca",
    RouteIntentCargoPreference.REFRIGERATED_CARGO.value: "Refrigerada",
    RouteIntentCargoPreference.BOTH.value: "Seca ou refrigerada",
}


def _intent_queryset(user):
    return scoped_driver_route_intent_queryset(
        user, PermissionCode.DRIVER_ROUTE_INTENTS_VIEW
    ).select_related("driver", "vehicle", "organization", "cancelled_by")


class DriverRouteIntentForm(forms.Form):
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    intent_type = forms.ChoiceField(
        choices=[(item.value, INTENT_TYPE_LABELS[item.value]) for item in DriverRouteIntentType],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    origin_city = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    origin_state = forms.CharField(
        max_length=2,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "UF"}),
    )
    destination_city = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    destination_state = forms.CharField(
        max_length=2,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "UF"}),
    )
    available_from = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
    )
    available_until = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
    )
    max_origin_deviation_km = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    max_destination_deviation_km = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    cargo_preference = forms.ChoiceField(
        required=False,
        choices=[("", "Sem preferência")]
        + [(item.value, CARGO_PREFERENCE_LABELS[item.value]) for item in RouteIntentCargoPreference],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["driver"].queryset = scoped_driver_queryset(
                user, PermissionCode.DRIVERS_VIEW
            ).order_by("full_name")
            self.fields["vehicle"].queryset = scoped_vehicle_queryset(
                user, PermissionCode.VEHICLES_VIEW
            ).order_by("plate")

    def to_data(self) -> DriverRouteIntentData:
        driver = self.cleaned_data["driver"]
        cargo = self.cleaned_data.get("cargo_preference") or None
        return DriverRouteIntentData(
            organization=driver.organization,
            driver=driver,
            vehicle=self.cleaned_data.get("vehicle"),
            intent_type=DriverRouteIntentType(self.cleaned_data["intent_type"]),
            origin_city=self.cleaned_data["origin_city"],
            origin_state=self.cleaned_data["origin_state"],
            destination_city=self.cleaned_data["destination_city"],
            destination_state=self.cleaned_data["destination_state"],
            available_from=self.cleaned_data["available_from"],
            available_until=self.cleaned_data["available_until"],
            max_origin_deviation_km=self.cleaned_data.get("max_origin_deviation_km"),
            max_destination_deviation_km=self.cleaned_data.get("max_destination_deviation_km"),
            cargo_preference=RouteIntentCargoPreference(cargo) if cargo else None,
            source=DriverRouteIntentSource.BACKOFFICE,
            notes=self.cleaned_data.get("notes", ""),
        )


class DriverRouteIntentListView(FilteredListView):
    template_name = "backoffice/pages/driver_route_intents/list.html"
    permission_code = PermissionCode.DRIVER_ROUTE_INTENTS_VIEW
    active_menu = "driver_route_intents"
    page_title = "Intenções de Rota"
    context_object_name = "route_intents"

    def get_queryset(self):
        queryset = _intent_queryset(self.request.user)
        status = self.request.GET.get("status", "").strip()
        intent_type = self.request.GET.get("intent_type", "").strip()
        query = self.request.GET.get("q", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        if intent_type:
            queryset = queryset.filter(intent_type=intent_type)
        if query:
            queryset = queryset.filter(
                django_models.Q(driver__full_name__icontains=query)
                | django_models.Q(origin_city__icontains=query)
                | django_models.Q(destination_city__icontains=query)
                | django_models.Q(vehicle__plate__icontains=query)
            )
        return queryset.order_by("-available_from", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_create"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVER_ROUTE_INTENTS_CREATE
        )
        context["status_labels"] = STATUS_LABELS
        context["intent_type_labels"] = INTENT_TYPE_LABELS
        context["cargo_preference_labels"] = CARGO_PREFERENCE_LABELS
        context["filters"] = {
            "status": self.request.GET.get("status", ""),
            "intent_type": self.request.GET.get("intent_type", ""),
            "q": self.request.GET.get("q", ""),
        }
        context["statuses"] = [item.value for item in DriverRouteIntentStatus]
        context["intent_types"] = [item.value for item in DriverRouteIntentType]
        intents = list(context["route_intents"])
        for intent in intents:
            apply_route_intent_expiration_if_needed(intent)
        context["route_intents"] = intents
        return context

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Intenções de Rota", None),
        )


class DriverRouteIntentDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/driver_route_intents/detail.html"
    context_object_name = "route_intent"
    permission_code = PermissionCode.DRIVER_ROUTE_INTENTS_VIEW
    active_menu = "driver_route_intents"
    page_title = "Intenção de Rota"

    def get_queryset(self):
        return _intent_queryset(self.request.user)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset=queryset)
        return apply_route_intent_expiration_if_needed(obj)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Intenções de Rota", reverse_lazy("backoffice:driver_route_intents")),
            (str(self.object), None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_labels"] = STATUS_LABELS
        context["intent_type_labels"] = INTENT_TYPE_LABELS
        context["cargo_preference_labels"] = CARGO_PREFERENCE_LABELS
        context["can_update"] = (
            self.object.status == DriverRouteIntentStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.DRIVER_ROUTE_INTENTS_UPDATE
            )
        )
        context["can_activate"] = (
            self.object.status == DriverRouteIntentStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.DRIVER_ROUTE_INTENTS_UPDATE
            )
        )
        context["can_cancel"] = self.object.status in {
            DriverRouteIntentStatus.DRAFT.value,
            DriverRouteIntentStatus.ACTIVE.value,
        } and user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVER_ROUTE_INTENTS_CANCEL
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:10]
        return context


class DriverRouteIntentCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/driver_route_intents/form.html"
    permission_code = PermissionCode.DRIVER_ROUTE_INTENTS_CREATE
    active_menu = "driver_route_intents"
    page_title = "Nova Intenção de Rota"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Intenções de Rota", reverse_lazy("backoffice:driver_route_intents")),
            ("Nova", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            initial = {}
            driver_pk = self.request.GET.get("driver")
            vehicle_pk = self.request.GET.get("vehicle")
            if driver_pk:
                initial["driver"] = driver_pk
            if vehicle_pk:
                initial["vehicle"] = vehicle_pk
            context["form"] = DriverRouteIntentForm(user=self.request.user, initial=initial)
        context["is_edit"] = False
        return context

    def post(self, request, *args, **kwargs):
        form = DriverRouteIntentForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                intent = create_driver_route_intent(data=form.to_data(), actor=request.user)
                return redirect("backoffice:driver_route_intent_detail", pk=intent.pk)
            except ValidationError as exc:
                if hasattr(exc, "error_dict"):
                    for field, errors in exc.error_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class DriverRouteIntentUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/driver_route_intents/form.html"
    permission_code = PermissionCode.DRIVER_ROUTE_INTENTS_UPDATE
    active_menu = "driver_route_intents"
    page_title = "Editar Intenção de Rota"

    def get_intent(self):
        return get_object_or_404(
            _intent_queryset(self.request.user),
            pk=self.kwargs["pk"],
            status=DriverRouteIntentStatus.DRAFT.value,
        )

    def get_breadcrumbs(self):
        intent = self.get_intent()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Intenções de Rota", reverse_lazy("backoffice:driver_route_intents")),
            (str(intent), reverse_lazy("backoffice:driver_route_intent_detail", args=[intent.pk])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        intent = self.get_intent()
        if "form" not in context:
            context["form"] = DriverRouteIntentForm(
                user=self.request.user,
                initial={
                    "driver": intent.driver_id,
                    "vehicle": intent.vehicle_id,
                    "intent_type": intent.intent_type,
                    "origin_city": intent.origin_city,
                    "origin_state": intent.origin_state,
                    "destination_city": intent.destination_city,
                    "destination_state": intent.destination_state,
                    "available_from": intent.available_from,
                    "available_until": intent.available_until,
                    "max_origin_deviation_km": intent.max_origin_deviation_km,
                    "max_destination_deviation_km": intent.max_destination_deviation_km,
                    "cargo_preference": intent.cargo_preference,
                    "notes": intent.notes,
                },
            )
        context["route_intent"] = intent
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        intent = self.get_intent()
        form = DriverRouteIntentForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                update_driver_route_intent(intent, data=form.to_data(), actor=request.user)
                return redirect("backoffice:driver_route_intent_detail", pk=intent.pk)
            except ValidationError as exc:
                if hasattr(exc, "error_dict"):
                    for field, errors in exc.error_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    form.add_error(None, exc)
        return render(
            request,
            self.template_name,
            self.get_context_data(form=form, route_intent=intent),
        )


class DriverRouteIntentActivateView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.DRIVER_ROUTE_INTENTS_UPDATE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        intent = get_object_or_404(_intent_queryset(request.user), pk=kwargs["pk"])
        try:
            activate_driver_route_intent(intent, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:driver_route_intent_detail", pk=intent.pk)


class DriverRouteIntentCancelView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.DRIVER_ROUTE_INTENTS_CANCEL
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        intent = get_object_or_404(_intent_queryset(request.user), pk=kwargs["pk"])
        reason = request.POST.get("reason", "")
        try:
            cancel_driver_route_intent(intent, actor=request.user, reason=reason)
        except ValidationError:
            pass
        return redirect("backoffice:driver_route_intent_detail", pk=intent.pk)
