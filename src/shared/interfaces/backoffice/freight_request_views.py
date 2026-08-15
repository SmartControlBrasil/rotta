from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models as django_models
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, TemplateView, View

from src.audit.infrastructure.django.models import AuditLog
from src.customers.infrastructure.django.models import Customer
from src.freights.application.services import (
    CargoData,
    FreightRequestData,
    StopData,
    assign_freight_request_owner,
    cancel_freight_request,
    change_freight_request_status,
    create_freight_request,
    submit_freight_request,
    update_freight_request,
)
from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightCargoType,
    FreightRequestPriority,
    FreightRequestStatus,
    FreightStopType,
)
from src.freights.domain.quote_state_machine import REQUEST_STATUSES_ALLOWING_QUOTE_CREATION
from src.freights.domain.state_machine import ALLOWED_STATUS_TRANSITIONS
from src.freights.infrastructure.django.models import FreightRequest, FreightRequestStop
from src.identity.domain.enums import PermissionCode
from src.vehicles.domain.enums import VehicleBodyType, VehicleType

from .authorization import (
    scoped_customer_queryset,
    scoped_freight_offer_queryset,
    scoped_freight_quote_queryset,
    scoped_freight_request_queryset,
    scoped_user_queryset,
    user_has_backoffice_permission,
)
from .views import BackofficeContextMixin, BackofficePermissionMixin, FilteredListView

STATUS_LABELS = {
    FreightRequestStatus.DRAFT.value: "Rascunho",
    FreightRequestStatus.SUBMITTED.value: "Enviada",
    FreightRequestStatus.UNDER_REVIEW.value: "Em análise",
    FreightRequestStatus.QUOTING.value: "Em cotação",
    FreightRequestStatus.READY_TO_PUBLISH.value: "Pronta para publicar",
    FreightRequestStatus.CANCELLED.value: "Cancelada",
    FreightRequestStatus.CLOSED.value: "Encerrada",
}

CARGO_PROFILE_LABELS = {
    FreightCargoProfile.DRY_CARGO.value: "Carga seca",
    FreightCargoProfile.REFRIGERATED_CARGO.value: "Refrigerada",
}


class FreightRequestForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    owner = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    priority = forms.ChoiceField(
        choices=[(item.value, item.value) for item in FreightRequestPriority],
        initial=FreightRequestPriority.NORMAL.value,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    handling_requirements = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    hazardous_material = forms.BooleanField(required=False)
    declared_cargo_value = forms.DecimalField(
        required=False,
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    currency = forms.CharField(
        initial="BRL",
        max_length=3,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    vehicle_type_required = forms.ChoiceField(
        required=False,
        choices=[("", "—")] + [(item.value, item.value) for item in VehicleType],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    body_type_required = forms.ChoiceField(
        required=False,
        choices=[("", "—")] + [(item.value, item.value) for item in VehicleBodyType],
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    pickup_postal_code = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_street = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_number = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_complement = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_district = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_city = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_state = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_country = forms.CharField(
        initial="BR", required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    pickup_instructions = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2})
    )
    pickup_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    pickup_window_start = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"})
    )
    pickup_window_end = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"})
    )

    delivery_postal_code = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_street = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_number = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_complement = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_district = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_city = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_state = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_country = forms.CharField(
        initial="BR", required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    delivery_instructions = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2})
    )
    delivery_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    delivery_window_start = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"})
    )
    delivery_window_end = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"})
    )

    cargo_description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 3})
    )
    cargo_type = forms.ChoiceField(
        choices=[(item.value, item.value) for item in FreightCargoType],
        initial=FreightCargoType.GENERAL_CARGO.value,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    cargo_profile = forms.ChoiceField(
        choices=[(item.value, item.value) for item in FreightCargoProfile],
        initial=FreightCargoProfile.DRY_CARGO.value,
        widget=forms.Select(attrs={"class": "form-control", "id": "id_cargo_profile"}),
    )
    weight_kg = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.001"}),
    )
    volume_m3 = forms.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.001"}),
    )
    package_count = forms.IntegerField(
        required=False, min_value=1, widget=forms.NumberInput(attrs={"class": "form-control"})
    )
    package_type = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    temperature_min_c = forms.DecimalField(
        required=False,
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control refrigeration-field", "step": "0.01"}
        ),
    )
    temperature_max_c = forms.DecimalField(
        required=False,
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control refrigeration-field", "step": "0.01"}
        ),
    )
    target_temperature_c = forms.DecimalField(
        required=False,
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control refrigeration-field", "step": "0.01"}
        ),
    )

    def __init__(self, *args, user=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model

        User = get_user_model()
        if user:
            self.fields["customer"].queryset = scoped_customer_queryset(
                user, PermissionCode.CUSTOMERS_VIEW
            ).order_by("legal_name")
            self.fields["owner"].queryset = scoped_user_queryset(
                user, PermissionCode.USERS_VIEW
            ).order_by("email")
            if not user_has_backoffice_permission(
                user, PermissionCode.FREIGHT_REQUESTS_ASSIGN_OWNER
            ):
                self.fields["owner"].disabled = True
        else:
            self.fields["customer"].queryset = Customer.objects.none()
            self.fields["owner"].queryset = User.objects.none()
        if instance:
            self._populate_from_instance(instance)

    def _populate_from_instance(self, instance: FreightRequest) -> None:
        self.fields["customer"].initial = instance.customer_id
        self.fields["owner"].initial = instance.owner_id
        self.fields["priority"].initial = instance.priority
        self.fields["instructions"].initial = instance.instructions
        self.fields["handling_requirements"].initial = instance.handling_requirements
        self.fields["hazardous_material"].initial = instance.hazardous_material
        self.fields["declared_cargo_value"].initial = instance.declared_cargo_value
        self.fields["currency"].initial = instance.currency
        self.fields["vehicle_type_required"].initial = instance.vehicle_type_required
        self.fields["body_type_required"].initial = instance.body_type_required
        pickup = instance.pickup_stop
        delivery = instance.delivery_stop
        if pickup:
            self.fields["pickup_postal_code"].initial = pickup.postal_code
            self.fields["pickup_street"].initial = pickup.street
            self.fields["pickup_number"].initial = pickup.number
            self.fields["pickup_complement"].initial = pickup.complement
            self.fields["pickup_district"].initial = pickup.district
            self.fields["pickup_city"].initial = pickup.city
            self.fields["pickup_state"].initial = pickup.state
            self.fields["pickup_country"].initial = pickup.country
            self.fields["pickup_instructions"].initial = pickup.instructions
            self.fields["pickup_date"].initial = pickup.scheduled_date
            self.fields["pickup_window_start"].initial = pickup.window_start
            self.fields["pickup_window_end"].initial = pickup.window_end
        if delivery:
            self.fields["delivery_postal_code"].initial = delivery.postal_code
            self.fields["delivery_street"].initial = delivery.street
            self.fields["delivery_number"].initial = delivery.number
            self.fields["delivery_complement"].initial = delivery.complement
            self.fields["delivery_district"].initial = delivery.district
            self.fields["delivery_city"].initial = delivery.city
            self.fields["delivery_state"].initial = delivery.state
            self.fields["delivery_country"].initial = delivery.country
            self.fields["delivery_instructions"].initial = delivery.instructions
            self.fields["delivery_date"].initial = delivery.scheduled_date
            self.fields["delivery_window_start"].initial = delivery.window_start
            self.fields["delivery_window_end"].initial = delivery.window_end
        if hasattr(instance, "cargo"):
            cargo = instance.cargo
            self.fields["cargo_description"].initial = cargo.description
            self.fields["cargo_type"].initial = cargo.cargo_type
            self.fields["cargo_profile"].initial = cargo.cargo_profile
            self.fields["weight_kg"].initial = cargo.weight_kg
            self.fields["volume_m3"].initial = cargo.volume_m3
            self.fields["package_count"].initial = cargo.package_count
            self.fields["package_type"].initial = cargo.package_type
            self.fields["temperature_min_c"].initial = cargo.temperature_min_c
            self.fields["temperature_max_c"].initial = cargo.temperature_max_c
            self.fields["target_temperature_c"].initial = cargo.target_temperature_c

    def clean_customer(self):
        customer = self.cleaned_data["customer"]
        return customer

    def build_payload(self, *, created_by, organization):
        cleaned = self.cleaned_data
        stops = (
            StopData(
                stop_type=FreightStopType.PICKUP,
                sequence=1,
                postal_code=cleaned.get("pickup_postal_code", ""),
                street=cleaned.get("pickup_street", ""),
                number=cleaned.get("pickup_number", ""),
                complement=cleaned.get("pickup_complement", ""),
                district=cleaned.get("pickup_district", ""),
                city=cleaned.get("pickup_city", ""),
                state=cleaned.get("pickup_state", ""),
                country=cleaned.get("pickup_country") or "BR",
                instructions=cleaned.get("pickup_instructions", ""),
                scheduled_date=cleaned.get("pickup_date"),
                window_start=cleaned.get("pickup_window_start"),
                window_end=cleaned.get("pickup_window_end"),
            ),
            StopData(
                stop_type=FreightStopType.DELIVERY,
                sequence=2,
                postal_code=cleaned.get("delivery_postal_code", ""),
                street=cleaned.get("delivery_street", ""),
                number=cleaned.get("delivery_number", ""),
                complement=cleaned.get("delivery_complement", ""),
                district=cleaned.get("delivery_district", ""),
                city=cleaned.get("delivery_city", ""),
                state=cleaned.get("delivery_state", ""),
                country=cleaned.get("delivery_country") or "BR",
                instructions=cleaned.get("delivery_instructions", ""),
                scheduled_date=cleaned.get("delivery_date"),
                window_start=cleaned.get("delivery_window_start"),
                window_end=cleaned.get("delivery_window_end"),
            ),
        )
        cargo = CargoData(
            description=cleaned.get("cargo_description", ""),
            cargo_type=FreightCargoType(cleaned["cargo_type"]),
            cargo_profile=FreightCargoProfile(cleaned["cargo_profile"]),
            weight_kg=cleaned.get("weight_kg"),
            volume_m3=cleaned.get("volume_m3"),
            package_count=cleaned.get("package_count"),
            package_type=cleaned.get("package_type", ""),
            temperature_min_c=cleaned.get("temperature_min_c"),
            temperature_max_c=cleaned.get("temperature_max_c"),
            target_temperature_c=cleaned.get("target_temperature_c"),
        )
        return FreightRequestData(
            organization=organization,
            customer=cleaned["customer"],
            created_by=created_by,
            owner=cleaned.get("owner") or created_by,
            priority=FreightRequestPriority(cleaned["priority"]),
            instructions=cleaned.get("instructions", ""),
            handling_requirements=cleaned.get("handling_requirements", ""),
            hazardous_material=cleaned.get("hazardous_material") or False,
            declared_cargo_value=cleaned.get("declared_cargo_value"),
            currency=cleaned.get("currency") or "BRL",
            vehicle_type_required=cleaned.get("vehicle_type_required") or "",
            body_type_required=cleaned.get("body_type_required") or "",
            stops=stops,
            cargo=cargo,
        )

    def build_update_changes(self):
        cleaned = self.cleaned_data
        stops = (
            StopData(
                stop_type=FreightStopType.PICKUP,
                sequence=1,
                postal_code=cleaned.get("pickup_postal_code", ""),
                street=cleaned.get("pickup_street", ""),
                number=cleaned.get("pickup_number", ""),
                complement=cleaned.get("pickup_complement", ""),
                district=cleaned.get("pickup_district", ""),
                city=cleaned.get("pickup_city", ""),
                state=cleaned.get("pickup_state", ""),
                country=cleaned.get("pickup_country") or "BR",
                instructions=cleaned.get("pickup_instructions", ""),
                scheduled_date=cleaned.get("pickup_date"),
                window_start=cleaned.get("pickup_window_start"),
                window_end=cleaned.get("pickup_window_end"),
            ),
            StopData(
                stop_type=FreightStopType.DELIVERY,
                sequence=2,
                postal_code=cleaned.get("delivery_postal_code", ""),
                street=cleaned.get("delivery_street", ""),
                number=cleaned.get("delivery_number", ""),
                complement=cleaned.get("delivery_complement", ""),
                district=cleaned.get("delivery_district", ""),
                city=cleaned.get("delivery_city", ""),
                state=cleaned.get("delivery_state", ""),
                country=cleaned.get("delivery_country") or "BR",
                instructions=cleaned.get("delivery_instructions", ""),
                scheduled_date=cleaned.get("delivery_date"),
                window_start=cleaned.get("delivery_window_start"),
                window_end=cleaned.get("delivery_window_end"),
            ),
        )
        cargo = CargoData(
            description=cleaned.get("cargo_description", ""),
            cargo_type=FreightCargoType(cleaned["cargo_type"]),
            cargo_profile=FreightCargoProfile(cleaned["cargo_profile"]),
            weight_kg=cleaned.get("weight_kg"),
            volume_m3=cleaned.get("volume_m3"),
            package_count=cleaned.get("package_count"),
            package_type=cleaned.get("package_type", ""),
            temperature_min_c=cleaned.get("temperature_min_c"),
            temperature_max_c=cleaned.get("temperature_max_c"),
            target_temperature_c=cleaned.get("target_temperature_c"),
        )
        return {
            "customer": cleaned["customer"],
            "owner": cleaned.get("owner"),
            "priority": FreightRequestPriority(cleaned["priority"]),
            "instructions": cleaned.get("instructions", ""),
            "handling_requirements": cleaned.get("handling_requirements", ""),
            "hazardous_material": cleaned.get("hazardous_material") or False,
            "declared_cargo_value": cleaned.get("declared_cargo_value"),
            "currency": cleaned.get("currency") or "BRL",
            "vehicle_type_required": cleaned.get("vehicle_type_required") or "",
            "body_type_required": cleaned.get("body_type_required") or "",
            "stops": stops,
            "cargo": cargo,
        }


def _freight_request_queryset(user):
    return (
        scoped_freight_request_queryset(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
        .select_related("customer", "owner", "organization", "created_by")
        .prefetch_related(
            Prefetch(
                "stops",
                queryset=FreightRequestStop.objects.order_by("sequence"),
            ),
            "cargo",
        )
    )


class FreightRequestListView(FilteredListView):
    template_name = "backoffice/pages/freight_requests/list.html"
    context_object_name = "freight_requests"
    permission_code = PermissionCode.FREIGHT_REQUESTS_VIEW
    active_menu = "freight_requests"
    page_title = "Solicitações de Transporte"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Solicitações de Transporte", None),
    )

    def get_queryset(self):
        queryset = _freight_request_queryset(self.request.user)
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        customer_id = self.request.GET.get("customer", "").strip()
        cargo_profile = self.request.GET.get("cargo_profile", "").strip()
        pickup_state = self.request.GET.get("pickup_state", "").strip().upper()
        delivery_state = self.request.GET.get("delivery_state", "").strip().upper()
        owner_id = self.request.GET.get("owner", "").strip()
        pickup_date = parse_date(self.request.GET.get("pickup_date", "").strip() or "")

        if query:
            queryset = queryset.filter(
                django_models.Q(reference_code__icontains=query)
                | django_models.Q(customer__legal_name__icontains=query)
                | django_models.Q(stops__city__icontains=query)
                | django_models.Q(cargo__description__icontains=query)
            ).distinct()
        if status:
            queryset = queryset.filter(status=status)
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        if cargo_profile:
            queryset = queryset.filter(cargo__cargo_profile=cargo_profile)
        if pickup_state:
            queryset = queryset.filter(
                stops__stop_type=FreightStopType.PICKUP.value,
                stops__state=pickup_state,
            )
        if delivery_state:
            queryset = queryset.filter(
                stops__stop_type=FreightStopType.DELIVERY.value,
                stops__state=delivery_state,
            )
        if owner_id:
            queryset = queryset.filter(owner_id=owner_id)
        if pickup_date:
            queryset = queryset.filter(
                stops__stop_type=FreightStopType.PICKUP.value,
                stops__scheduled_date=pickup_date,
            )
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = scoped_freight_request_queryset(
            self.request.user, PermissionCode.FREIGHT_REQUESTS_VIEW
        )
        stats = base_qs.aggregate(
            total=Count("id"),
            drafts=Count("id", filter=Q(status=FreightRequestStatus.DRAFT.value)),
            submitted=Count("id", filter=Q(status=FreightRequestStatus.SUBMITTED.value)),
            under_review=Count("id", filter=Q(status=FreightRequestStatus.UNDER_REVIEW.value)),
            cancelled=Count("id", filter=Q(status=FreightRequestStatus.CANCELLED.value)),
            refrigerated=Count(
                "id",
                filter=Q(cargo__cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value),
            ),
        )
        context["kpis"] = stats
        context["status_labels"] = STATUS_LABELS
        context["cargo_profile_labels"] = CARGO_PROFILE_LABELS
        context["statuses"] = [
            FreightRequestStatus.DRAFT,
            FreightRequestStatus.SUBMITTED,
            FreightRequestStatus.UNDER_REVIEW,
            FreightRequestStatus.CANCELLED,
        ]
        context["cargo_profiles"] = list(FreightCargoProfile)
        context["customers"] = scoped_customer_queryset(
            self.request.user, PermissionCode.CUSTOMERS_VIEW
        ).order_by("legal_name")
        context["owners"] = scoped_user_queryset(
            self.request.user, PermissionCode.USERS_VIEW
        ).order_by("email")
        context["can_create"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_REQUESTS_CREATE
        )
        return context


class FreightRequestDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/freight_requests/detail.html"
    context_object_name = "freight_request"
    permission_code = PermissionCode.FREIGHT_REQUESTS_VIEW
    active_menu = "freight_requests"
    page_title = "Detalhe da Solicitação"

    def get_queryset(self):
        return _freight_request_queryset(self.request.user)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Solicitações de Transporte", reverse_lazy("backoffice:freight_requests")),
            (self.object.reference_code, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current = FreightRequestStatus(self.object.status)
        context["status_labels"] = STATUS_LABELS
        context["cargo_profile_labels"] = CARGO_PROFILE_LABELS
        context["allowed_transitions"] = sorted(
            ALLOWED_STATUS_TRANSITIONS.get(current, frozenset()),
            key=lambda item: item.value,
        )
        context["can_edit"] = (
            self.object.status == FreightRequestStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_REQUESTS_UPDATE
            )
        )
        context["can_submit"] = (
            self.object.status == FreightRequestStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_REQUESTS_SUBMIT
            )
        )
        context["can_cancel"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_REQUESTS_CANCEL
        ) and current in {
            FreightRequestStatus.DRAFT,
            FreightRequestStatus.SUBMITTED,
            FreightRequestStatus.UNDER_REVIEW,
        }
        context["can_change_status"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_REQUESTS_CHANGE_STATUS
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:12]
        context["quotes"] = (
            scoped_freight_quote_queryset(self.request.user, PermissionCode.FREIGHT_QUOTES_VIEW)
            .filter(freight_request=self.object)
            .order_by("-version")
        )
        context["can_create_quote"] = (
            self.object.status in REQUEST_STATUSES_ALLOWING_QUOTE_CREATION
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_QUOTES_CREATE
            )
        )
        context["can_view_quotes"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_VIEW
        )
        context["offers"] = (
            scoped_freight_offer_queryset(self.request.user, PermissionCode.FREIGHT_OFFERS_VIEW)
            .filter(freight_request=self.object)
            .order_by("-created_at")
        )
        context["can_create_offer"] = (
            self.object.status == FreightRequestStatus.READY_TO_PUBLISH.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_OFFERS_CREATE
            )
        )
        context["can_view_offers"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OFFERS_VIEW
        )
        return context


class FreightRequestCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/freight_requests/form.html"
    permission_code = PermissionCode.FREIGHT_REQUESTS_CREATE
    active_menu = "freight_requests"
    page_title = "Nova Solicitação de Transporte"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Solicitações de Transporte", reverse_lazy("backoffice:freight_requests")),
        ("Nova Solicitação", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = FreightRequestForm(user=self.request.user)
        context["is_edit"] = False
        return context

    def post(self, request, *args, **kwargs):
        form = FreightRequestForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                customer = form.cleaned_data["customer"]
                data = form.build_payload(
                    created_by=request.user, organization=customer.organization
                )
                freight_request = create_freight_request(data=data, actor=request.user)
                return redirect("backoffice:freight_request_detail", pk=freight_request.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class FreightRequestUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/freight_requests/form.html"
    permission_code = PermissionCode.FREIGHT_REQUESTS_UPDATE
    active_menu = "freight_requests"
    page_title = "Editar Solicitação de Transporte"

    def get_object(self):
        return get_object_or_404(_freight_request_queryset(self.request.user), pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Solicitações de Transporte", reverse_lazy("backoffice:freight_requests")),
            (obj.reference_code, reverse_lazy("backoffice:freight_request_detail", args=[obj.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = FreightRequestForm(user=self.request.user, instance=obj)
        context["is_edit"] = True
        context["freight_request"] = obj
        return context

    def post(self, request, *args, **kwargs):
        freight_request = self.get_object()
        form = FreightRequestForm(request.POST, user=request.user, instance=freight_request)
        if form.is_valid():
            try:
                changes = form.build_update_changes()
                if "owner" in form.changed_data and not user_has_backoffice_permission(
                    request.user, PermissionCode.FREIGHT_REQUESTS_ASSIGN_OWNER
                ):
                    raise PermissionDenied
                update_freight_request(freight_request, actor=request.user, **changes)
                return redirect("backoffice:freight_request_detail", pk=freight_request.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class FreightRequestSubmitView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_REQUESTS_SUBMIT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        freight_request = get_object_or_404(
            _freight_request_queryset(request.user), pk=kwargs["pk"]
        )
        try:
            submit_freight_request(freight_request, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_request_detail", pk=freight_request.pk)


class FreightRequestCancelView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_REQUESTS_CANCEL
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        freight_request = get_object_or_404(
            _freight_request_queryset(request.user), pk=kwargs["pk"]
        )
        reason = request.POST.get("cancellation_reason", "")
        try:
            cancel_freight_request(freight_request, reason=reason, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_request_detail", pk=freight_request.pk)


class FreightRequestStatusChangeView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_REQUESTS_CHANGE_STATUS
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        freight_request = get_object_or_404(
            _freight_request_queryset(request.user), pk=kwargs["pk"]
        )
        status_value = request.POST.get("status", "")
        if status_value in [status.value for status in FreightRequestStatus]:
            try:
                change_freight_request_status(
                    freight_request,
                    status=FreightRequestStatus(status_value),
                    actor=request.user,
                )
            except ValidationError:
                pass
        return redirect("backoffice:freight_request_detail", pk=freight_request.pk)


class FreightRequestAssignOwnerView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_REQUESTS_ASSIGN_OWNER
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        freight_request = get_object_or_404(
            _freight_request_queryset(request.user), pk=kwargs["pk"]
        )
        owner_id = request.POST.get("owner_id", "")
        owner = get_object_or_404(
            scoped_user_queryset(request.user, PermissionCode.USERS_VIEW),
            pk=owner_id,
        )
        assign_freight_request_owner(freight_request, owner=owner, actor=request.user)
        return redirect("backoffice:freight_request_detail", pk=freight_request.pk)
