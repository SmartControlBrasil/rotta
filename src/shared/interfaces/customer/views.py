from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from typing import Any

from src.customers.infrastructure.django.models import Customer
from src.organizations.infrastructure.django.models import Membership
from src.freights.infrastructure.django.models import FreightRequest
from src.freights.domain.enums import FreightRequestStatus, FreightCargoProfile
from src.customers.application.services import create_customer_freight_request


class CustomerRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        
        customer = Customer.objects.filter(owner=request.user).first()
        if not customer:
            active_membership = Membership.objects.filter(
                user=request.user,
                status="ACTIVE",
                organization__type="CUSTOMER"
            ).first()
            if active_membership:
                customer = Customer.objects.filter(organization=active_membership.organization).first()
                
        if not customer:
            raise PermissionDenied("Acesso negado: Usuário não possui perfil ou vínculo de cliente ativo.")
            
        request.customer = customer
        request.organization = customer.organization
        return super().dispatch(request, *args, **kwargs)


class CustomerDashboardView(CustomerRequiredMixin, TemplateView):
    template_name = "customer/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = FreightRequest.objects.filter(customer=self.request.customer)
        
        context["total_freights"] = qs.count()
        context["in_progress_freights"] = qs.filter(status=FreightRequestStatus.DRAFT.value).count()
        context["awaiting_freights"] = qs.filter(status__in=[
            FreightRequestStatus.SUBMITTED.value,
            FreightRequestStatus.UNDER_REVIEW.value,
            FreightRequestStatus.QUOTING.value,
            FreightRequestStatus.READY_TO_PUBLISH.value
        ]).count()
        context["completed_freights"] = qs.filter(status=FreightRequestStatus.CLOSED.value).count()
        
        recent_requests = qs.order_by("-created_at")[:5]
        context["recent_requests"] = [self._serialize(req) for req in recent_requests]
        return context

    def _serialize(self, req):
        pickup = req.pickup_stop
        delivery = req.delivery_stop
        cargo = getattr(req, "cargo", None)
        return {
            "id": str(req.id),
            "status": req.status,
            "status_label": self._get_status_label(req.status),
            "reference_code": req.reference_code,
            "origin": f"{pickup.city} - {pickup.state}" if pickup else "-",
            "destination": f"{delivery.city} - {delivery.state}" if delivery else "-",
            "scheduled_date": pickup.scheduled_date if pickup else None,
            "cargo_description": cargo.description if cargo else "-",
            "weight_kg": cargo.weight_kg if cargo else None,
            "refrigerated": cargo.cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value if cargo else False,
            "created_at": req.created_at,
        }

    def _get_status_label(self, status):
        labels = {
            "DRAFT": "Rascunho",
            "SUBMITTED": "Solicitação Recebida",
            "REQUESTED": "Solicitação Recebida",
            "QUOTED": "Cotação Disponível",
            "ASSIGNED": "Motorista Definido",
            "IN_TRANSIT": "Em Transporte",
            "DELIVERED": "Entregue",
            "CANCELLED": "Cancelado",
        }
        return labels.get(status, status)


class CustomerFreightRequestListView(CustomerRequiredMixin, ListView):
    template_name = "customer/freight_requests_list.html"
    context_object_name = "freight_requests"
    
    def get_queryset(self):
        return FreightRequest.objects.filter(customer=self.request.customer).order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dashboard = CustomerDashboardView()
        context["serialized_requests"] = [dashboard._serialize(req) for req in context["freight_requests"]]
        return context


class CustomerFreightRequestDetailView(CustomerRequiredMixin, DetailView):
    template_name = "customer/freight_request_detail.html"
    context_object_name = "freight_request"

    def get_object(self, queryset=None):
        return get_object_or_404(
            FreightRequest.objects.filter(customer=self.request.customer),
            pk=self.kwargs.get("uuid")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dashboard = CustomerDashboardView()
        context["serialized"] = dashboard._serialize(self.object)
        return context


class CustomerFreightRequestCreateView(CustomerRequiredMixin, View):
    def get(self, request):
        return render(request, "customer/freight_request_new.html")

    def post(self, request):
        origin = request.POST.get("origin")
        destination = request.POST.get("destination")
        service_type = request.POST.get("service_type", "ON_DEMAND")
        when = request.POST.get("when")
        cargo_description = request.POST.get("cargo_description")
        weight_kg = request.POST.get("weight_kg")
        volume_m3 = request.POST.get("volume_m3")
        refrigerated = request.POST.get("refrigerated") == "on"
        notes = request.POST.get("notes")
        contact = request.POST.get("contact")

        errors = {}
        if not origin:
            errors["origin"] = "Origem é obrigatória."
        if not destination:
            errors["destination"] = "Destino é obrigatório."
        if not cargo_description:
            errors["cargo_description"] = "A descrição da carga é obrigatória."
        if not weight_kg:
            errors["weight_kg"] = "O peso aproximado é obrigatório."

        payload = {
            "origin": origin,
            "destination": destination,
            "service_type": service_type,
            "cargo": {
                "description": cargo_description,
                "weight_kg": weight_kg,
                "volume_m3": volume_m3 if volume_m3 else None,
                "refrigerated": refrigerated,
            },
            "notes": notes,
            "contact": contact,
        }
        if service_type == "SCHEDULED":
            payload["when"] = when

        if errors:
            return render(request, "customer/freight_request_new.html", {
                "errors": errors,
                "payload": payload,
            })

        try:
            req = create_customer_freight_request(
                actor=request.user,
                customer=request.customer,
                payload=payload
            )
            return redirect(reverse("customer:freight_request_detail", kwargs={"uuid": req.id}))
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else str(e)
            return render(request, "customer/freight_request_new.html", {
                "non_field_errors": f"Erro de validação: {msg}",
                "payload": payload,
            })
        except Exception as e:
            return render(request, "customer/freight_request_new.html", {
                "non_field_errors": f"Erro inesperado: {str(e)}",
                "payload": payload,
            })
