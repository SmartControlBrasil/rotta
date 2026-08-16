from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import DetailView
from django.db.models import QuerySet

from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import FreightCargoProfile, FreightCargoType, FreightRequestStatus
from src.freights.infrastructure.django.models import FreightRequestCargo, FreightOperation, FreightOffer
from .authorization import scoped_freight_request_cargo_queryset, scoped_customer_queryset
from .views import BackofficeContextMixin, BackofficePermissionMixin, FilteredListView

CARGO_PROFILE_LABELS = {
    FreightCargoProfile.DRY_CARGO.value: "Carga seca",
    FreightCargoProfile.REFRIGERATED_CARGO.value: "Refrigerada",
}

STATUS_LABELS = {
    FreightRequestStatus.DRAFT.value: "Rascunho",
    FreightRequestStatus.SUBMITTED.value: "Enviada",
    FreightRequestStatus.UNDER_REVIEW.value: "Em análise",
    FreightRequestStatus.QUOTING.value: "Em cotação",
    FreightRequestStatus.READY_TO_PUBLISH.value: "Pronta para publicação",
    FreightRequestStatus.CLOSED.value: "Fechada",
    FreightRequestStatus.CANCELLED.value: "Cancelada",
}

class FreightRequestCargoListView(FilteredListView):
    template_name = "backoffice/pages/cargas/list.html"
    context_object_name = "cargas"
    permission_code = PermissionCode.LOADS_VIEW
    active_menu = "loads"
    page_title = "Cargas"

    def get_queryset(self) -> QuerySet:
        user = self.request.user
        queryset = scoped_freight_request_cargo_queryset(user, self.permission_code)
        
        customer_id = self.request.GET.get("customer")
        if customer_id:
            queryset = queryset.filter(freight_request__customer_id=customer_id)
            
        cargo_type = self.request.GET.get("cargo_type")
        if cargo_type:
            queryset = queryset.filter(cargo_type=cargo_type)
            
        cargo_profile = self.request.GET.get("cargo_profile")
        if cargo_profile:
            queryset = queryset.filter(cargo_profile=cargo_profile)
            
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(freight_request__status=status)
            
        start_date = self.request.GET.get("start_date")
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        end_date = self.request.GET.get("end_date")
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
            
        return queryset.order_by("-created_at")

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Cargas", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        context["cargo_profile_labels"] = CARGO_PROFILE_LABELS
        context["status_labels"] = STATUS_LABELS
        context["cargo_profiles"] = [p.value for p in FreightCargoProfile]
        context["cargo_types"] = [t.value for t in FreightCargoType]
        context["statuses"] = [s.value for s in FreightRequestStatus]
        context["customers"] = scoped_customer_queryset(user, PermissionCode.CUSTOMERS_VIEW.value).order_by("legal_name")
        
        return context


class FreightRequestCargoDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/cargas/detail.html"
    context_object_name = "cargo"
    permission_code = PermissionCode.LOADS_VIEW
    active_menu = "loads"
    page_title = "Detalhe da Carga"

    def get_queryset(self) -> QuerySet:
        return scoped_freight_request_cargo_queryset(self.request.user, self.permission_code)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Cargas", reverse_lazy("backoffice:cargas")),
            (str(self.object.id)[:8], None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cargo = self.object
        request = cargo.freight_request
        
        context["cargo_profile_labels"] = CARGO_PROFILE_LABELS
        context["status_labels"] = STATUS_LABELS
        
        if hasattr(request, "stops"):
            context["stops"] = request.stops.all().order_by("sequence")
        else:
            context["stops"] = []
            
        offers = FreightOffer.objects.filter(freight_request=request).order_by("-created_at")
        context["offers"] = offers
        
        operation = FreightOperation.objects.filter(selection__offer__freight_request=request).first()
        context["operation"] = operation
        
        return context
