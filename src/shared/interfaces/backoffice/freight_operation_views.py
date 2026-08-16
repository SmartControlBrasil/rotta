from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import DetailView, View
from django.utils import timezone
from django.db.models import QuerySet

from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import OperationStatus
from src.freights.infrastructure.django.models import FreightOperation
from src.freights.application.operation_services import (
    change_operation_status,
    report_operation_incident,
    cancel_operation,
    record_proof_of_delivery,
)
from .authorization import scoped_freight_operations_queryset, user_has_backoffice_permission
from .views import BackofficeContextMixin, BackofficePermissionMixin, FilteredListView

STATUS_LABELS = {
    OperationStatus.ASSIGNED.value: "Designada",
    "DRIVER_EN_ROUTE_TO_PICKUP": "Motorista a caminho da coleta",
    "ARRIVED_AT_PICKUP": "Motorista na coleta",
    "LOADING": "Carregando",
    "IN_TRANSIT": "Em trânsito",
    "ARRIVED_AT_DELIVERY": "Motorista no destino",
    "UNLOADING": "Descarregando",
    "DELIVERED": "Entregue",
    "CANCELLED": "Cancelada",
}

STATUS_BADGE_CLASSES = {
    OperationStatus.ASSIGNED.value: "badge-primary",
    "DRIVER_EN_ROUTE_TO_PICKUP": "badge-info",
    "ARRIVED_AT_PICKUP": "badge-warning",
    "LOADING": "badge-warning",
    "IN_TRANSIT": "badge-secondary",
    "ARRIVED_AT_DELIVERY": "badge-info",
    "UNLOADING": "badge-warning",
    "DELIVERED": "badge-success",
    "CANCELLED": "badge-danger",
}

NEXT_STATUS_TRANSITIONS = {
    OperationStatus.ASSIGNED.value: (OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP, "Motorista a caminho da coleta"),
    OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP.value: (OperationStatus.ARRIVED_AT_PICKUP, "Confirmar chegada à coleta"),
    OperationStatus.ARRIVED_AT_PICKUP.value: (OperationStatus.LOADING, "Iniciar carregamento"),
    OperationStatus.LOADING.value: (OperationStatus.IN_TRANSIT, "Iniciar viagem"),
    OperationStatus.IN_TRANSIT.value: (OperationStatus.ARRIVED_AT_DELIVERY, "Confirmar chegada à entrega"),
    OperationStatus.ARRIVED_AT_DELIVERY.value: (OperationStatus.UNLOADING, "Iniciar descarregamento"),
    OperationStatus.UNLOADING.value: (OperationStatus.DELIVERED, "Concluir entrega"),
}


class FreightOperationListView(FilteredListView):
    template_name = "backoffice/pages/freight_operations/list.html"
    context_object_name = "freight_operations"
    permission_code = PermissionCode.FREIGHT_OPERATIONS_VIEW
    active_menu = "freight_operations"
    page_title = "Operações"

    def get_queryset(self) -> QuerySet:
        user = self.request.user
        queryset = scoped_freight_operations_queryset(user, self.permission_code)
        
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)
            
        carrier_id = self.request.GET.get("carrier")
        if carrier_id:
            queryset = queryset.filter(carrier_id=carrier_id)
            
        driver_id = self.request.GET.get("driver")
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)
            
        return queryset.order_by("-created_at")

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Operações", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        from .authorization import scoped_carrier_queryset, scoped_driver_queryset
        
        context["status_labels"] = STATUS_LABELS
        context["status_badge_classes"] = STATUS_BADGE_CLASSES
        context["statuses"] = [status.value for status in OperationStatus]
        
        context["carriers"] = scoped_carrier_queryset(user, PermissionCode.CARRIERS_VIEW.value).order_by("trade_name")
        context["drivers"] = scoped_driver_queryset(user, PermissionCode.DRIVERS_VIEW.value).order_by("full_name")
        
        return context


class FreightOperationDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/freight_operations/detail.html"
    context_object_name = "operation"
    permission_code = PermissionCode.FREIGHT_OPERATIONS_VIEW
    active_menu = "freight_operations"
    page_title = "Detalhe da Operação"

    def get_queryset(self) -> QuerySet:
        return scoped_freight_operations_queryset(self.request.user, self.permission_code)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Operações", reverse_lazy("backoffice:freight_operations")),
            (str(self.object.id)[:8], None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        operation = self.object
        current_status = operation.status
        
        next_transition = NEXT_STATUS_TRANSITIONS.get(current_status)
        if next_transition:
            next_status, next_label = next_transition
            context["next_status"] = next_status.value
            context["next_label"] = next_label
        else:
            context["next_status"] = None
            context["next_label"] = None
            
        context["can_change_status"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS
        )
        context["can_report_incident"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OPERATIONS_REPORT_INCIDENT
        )
        context["can_cancel"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OPERATIONS_CANCEL
        ) and current_status not in (OperationStatus.DELIVERED.value, OperationStatus.CANCELLED.value)
        
        from src.freights.infrastructure.django.models import ProofOfDelivery
        has_pod = ProofOfDelivery.objects.filter(operation=operation).exists()
        context["has_pod"] = has_pod
        context["can_record_pod"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OPERATIONS_RECORD_POD
        ) and current_status == OperationStatus.UNLOADING.value and not has_pod

        if has_pod:
            context["pod"] = ProofOfDelivery.objects.get(operation=operation)
        else:
            context["pod"] = None

        context["status_labels"] = STATUS_LABELS
        context["status_badge_classes"] = STATUS_BADGE_CLASSES
        context["events"] = operation.events.all().order_by("created_at")
        
        if hasattr(operation.selection.offer.freight_request, 'stops'):
            context["stops"] = operation.selection.offer.freight_request.stops.all().order_by("sequence")
        else:
            context["stops"] = []

        context["can_view_tracking"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.TRACKING_VIEW
        )
        if context["can_view_tracking"]:
            latest_session = operation.tracking_sessions.first()
            context["tracking_session"] = latest_session
            if latest_session:
                points_qs = latest_session.location_points.order_by("-recorded_at")
                context["points_count"] = points_qs.count()
                context["last_point"] = points_qs.first()
                context["last_points"] = list(points_qs[:5])
            else:
                context["points_count"] = 0
                context["last_point"] = None
                context["last_points"] = []
            
        return context


class FreightOperationAdvanceStatusView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS
    http_method_names = ["post"]

    def post(self, request, pk):
        operation = get_object_or_404(
            scoped_freight_operations_queryset(request.user, PermissionCode.FREIGHT_OPERATIONS_VIEW.value),
            pk=pk
        )
        next_status_val = request.POST.get("next_status")
        if not next_status_val:
            messages.error(request, "Status de destino não informado.")
            return redirect("backoffice:freight_operation_detail", pk=pk)
            
        try:
            next_status = OperationStatus(next_status_val)
            change_operation_status(
                operation_id=operation.id,
                new_status=next_status,
                actor=request.user,
            )
            messages.success(request, f"Status da operação avançado com sucesso.")
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else str(e)
            messages.error(request, f"Erro ao avançar status: {msg}")
        except Exception as e:
            messages.error(request, f"Erro inesperado: {str(e)}")
            
        return redirect("backoffice:freight_operation_detail", pk=pk)


class FreightOperationReportIncidentView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OPERATIONS_REPORT_INCIDENT
    http_method_names = ["post"]

    def post(self, request, pk):
        operation = get_object_or_404(
            scoped_freight_operations_queryset(request.user, PermissionCode.FREIGHT_OPERATIONS_VIEW.value),
            pk=pk
        )
        description = request.POST.get("description")
        if not description:
            messages.error(request, "Descrição do incidente é obrigatória.")
            return redirect("backoffice:freight_operation_detail", pk=pk)
            
        try:
            report_operation_incident(
                operation_id=operation.id,
                description=description,
                actor=request.user,
            )
            messages.success(request, "Incidente registrado com sucesso.")
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else str(e)
            messages.error(request, f"Erro ao registrar incidente: {msg}")
        except Exception as e:
            messages.error(request, f"Erro inesperado: {str(e)}")
            
        return redirect("backoffice:freight_operation_detail", pk=pk)


class FreightOperationCancelView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OPERATIONS_CANCEL
    http_method_names = ["post"]

    def post(self, request, pk):
        operation = get_object_or_404(
            scoped_freight_operations_queryset(request.user, PermissionCode.FREIGHT_OPERATIONS_VIEW.value),
            pk=pk
        )
        reason = request.POST.get("reason")
        if not reason:
            messages.error(request, "Motivo do cancelamento é obrigatório.")
            return redirect("backoffice:freight_operation_detail", pk=pk)
            
        try:
            cancel_operation(
                operation_id=operation.id,
                reason=reason,
                actor=request.user,
            )
            messages.success(request, "Operação cancelada com sucesso.")
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else str(e)
            messages.error(request, f"Erro ao cancelar operação: {msg}")
        except Exception as e:
            messages.error(request, f"Erro inesperado: {str(e)}")
            
        return redirect("backoffice:freight_operation_detail", pk=pk)


class FreightOperationRecordPODView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OPERATIONS_RECORD_POD
    http_method_names = ["post"]

    def post(self, request, pk):
        operation = get_object_or_404(
            scoped_freight_operations_queryset(request.user, PermissionCode.FREIGHT_OPERATIONS_VIEW.value),
            pk=pk
        )
        receiver_name = request.POST.get("receiver_name")
        delivered_at_str = request.POST.get("delivered_at")
        notes = request.POST.get("notes", "")

        if not receiver_name or not delivered_at_str:
            messages.error(request, "Nome do recebedor e data de entrega são obrigatórios.")
            return redirect("backoffice:freight_operation_detail", pk=pk)

        try:
            delivered_at = timezone.datetime.fromisoformat(delivered_at_str)
            if timezone.is_naive(delivered_at):
                delivered_at = timezone.make_aware(delivered_at)
        except ValueError:
            messages.error(request, "Formato de data de entrega inválido.")
            return redirect("backoffice:freight_operation_detail", pk=pk)

        try:
            record_proof_of_delivery(
                operation_id=operation.id,
                receiver_name=receiver_name,
                delivered_at=delivered_at,
                notes=notes,
                actor=request.user,
            )
            messages.success(request, "Proof of Delivery (POD) registrado com sucesso.")
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else str(e)
            messages.error(request, f"Erro ao registrar POD: {msg}")
        except Exception as e:
            messages.error(request, f"Erro inesperado: {str(e)}")

        return redirect("backoffice:freight_operation_detail", pk=pk)
