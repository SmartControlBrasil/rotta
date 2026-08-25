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
        
        # select_related & prefetch_related for performance
        queryset = queryset.select_related(
            "driver",
            "vehicle",
            "organization",
            "selection__offer__freight_request__customer",
        ).prefetch_related(
            "stops"
        )

        # Annotate with last activity timestamp (1. latest event occurred_at, 2. latest tracking point, 3. updated_at)
        from src.freights.infrastructure.django.models import FreightOperationEvent, LocationPoint
        from django.db.models import Subquery, OuterRef
        from django.db.models.functions import Coalesce, Greatest

        latest_event_sub = Subquery(
            FreightOperationEvent.objects.filter(operation_id=OuterRef("pk"))
            .order_by("-occurred_at")
            .values("occurred_at")[:1]
        )
        latest_location_sub = Subquery(
            LocationPoint.objects.filter(operation_id=OuterRef("pk"))
            .order_by("-recorded_at")
            .values("recorded_at")[:1]
        )
        queryset = queryset.annotate(
            latest_event_ts=latest_event_sub,
            latest_location_ts=latest_location_sub,
        )
        queryset = queryset.annotate(
            last_activity_ts=Greatest(
                Coalesce("latest_event_ts", "updated_at"),
                Coalesce("latest_location_ts", "updated_at"),
                "updated_at",
            )
        )

        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)
            
        carrier_id = self.request.GET.get("carrier")
        if carrier_id:
            queryset = queryset.filter(carrier_id=carrier_id)
            
        driver_id = self.request.GET.get("driver")
        if driver_id:
            queryset = queryset.filter(driver_id=driver_id)

        vehicle_id = self.request.GET.get("vehicle")
        if vehicle_id:
            queryset = queryset.filter(vehicle_id=vehicle_id)

        origin = self.request.GET.get("origin")
        if origin:
            queryset = queryset.filter(source_type=origin)

        date_start = self.request.GET.get("date_start")
        if date_start:
            queryset = queryset.filter(created_at__date__gte=date_start)

        date_end = self.request.GET.get("date_end")
        if date_end:
            queryset = queryset.filter(created_at__date__lte=date_end)

        risk_level = self.request.GET.get("risk_level")
        from src.intelligence.infrastructure.django.models import IntelligenceAssessmentRecord
        from django.db.models import OuterRef, Subquery
        
        latest_risk_level = Subquery(
            IntelligenceAssessmentRecord.objects.filter(
                operation_id=OuterRef("pk")
            ).order_by("-assessed_at").values("risk_level")[:1]
        )
        queryset = queryset.annotate(latest_risk_level=latest_risk_level)
        if risk_level:
            queryset = queryset.filter(latest_risk_level=risk_level)

        # Search
        search = self.request.GET.get("search")
        if search:
            search = search.strip()
            from django.db.models import Q
            from django.db.models.functions import Cast
            from django.db.models import CharField
            import uuid
            import re
            
            q_objects = Q(driver__full_name__icontains=search) | \
                        Q(vehicle__plate__icontains=search) | \
                        Q(selection__offer__reference_code__icontains=search)
            
            try:
                uuid_search = uuid.UUID(search)
                q_objects |= Q(id=uuid_search)
            except ValueError:
                if re.match(r'^[a-fA-F0-9\-]+$', search):
                    queryset = queryset.annotate(id_str=Cast("id", output_field=CharField()))
                    q_objects |= Q(id_str__icontains=search)
            
            queryset = queryset.filter(q_objects)

        # Ordering
        order_by = self.request.GET.get("order_by")
        if order_by == "risk":
            latest_risk_score = Subquery(
                IntelligenceAssessmentRecord.objects.filter(
                    operation_id=OuterRef("pk")
                ).order_by("-assessed_at").values("risk_score")[:1]
            )
            from django.db.models.functions import Coalesce
            queryset = queryset.annotate(
                latest_risk_score=Coalesce(latest_risk_score, -1.0)
            ).order_by("-latest_risk_score")
        elif order_by == "SLA":
            from django.db.models.functions import Coalesce
            queryset = queryset.annotate(
                order_delay=Coalesce("delay_minutes", -999999)
            ).order_by("-order_delay")
        elif order_by == "updated_at":
            queryset = queryset.order_by("-last_activity_ts")
        elif order_by == "status":
            queryset = queryset.order_by("status")
        else:
            queryset = queryset.order_by("-created_at")

        return queryset

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Operações", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        from .authorization import scoped_carrier_queryset, scoped_driver_queryset, scoped_vehicle_queryset
        from src.freights.application.sla_service import SLAService, SLAState
        
        context["status_labels"] = STATUS_LABELS
        context["status_badge_classes"] = STATUS_BADGE_CLASSES
        context["statuses"] = [status.value for status in OperationStatus]
        
        context["carriers"] = scoped_carrier_queryset(user, PermissionCode.CARRIERS_VIEW.value).order_by("trade_name")
        context["drivers"] = scoped_driver_queryset(user, PermissionCode.DRIVERS_VIEW.value).order_by("full_name")
        context["vehicles"] = scoped_vehicle_queryset(user, PermissionCode.VEHICLES_VIEW.value).order_by("plate")
        context["origins"] = [("MARKETPLACE", "Marketplace"), ("CONTRACTED_ROUTE", "Rota Contratada"), ("MANUAL", "Manual"), ("API", "API")]

        # Batch load latest assessments to prevent N+1 queries
        operations = list(context["freight_operations"])
        if operations:
            op_ids = [str(op.id) for op in operations]
            from src.intelligence.application.query_services import OperationIntelligenceQueryService
            from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
            repo = DjangoIntelligenceSnapshotRepository()
            query_service = OperationIntelligenceQueryService(repo)
            
            assessments_map = query_service.get_latest_assessments_for_operations(op_ids, user)
            for op in operations:
                op.intelligence = assessments_map.get(str(op.id))
                
                # 1. Next Stop (first stop not completed/cancelled)
                # stops.all() uses prefetched cache
                all_stops = sorted(list(op.stops.all()), key=lambda s: s.sequence)
                next_stop = None
                for stop in all_stops:
                    if stop.status not in ["COMPLETED", "CANCELLED"]:
                        next_stop = stop
                        break
                op.next_stop_object = next_stop
                if next_stop:
                    op.next_stop_display = f"{next_stop.city}/{next_stop.state}"
                elif all_stops:
                    op.next_stop_display = "Concluída"
                else:
                    op.next_stop_display = "-"
                
                # 2. SLA State
                try:
                    sla_res = SLAService.compute(op)
                    op.sla_state = sla_res.state.value if (sla_res and sla_res.state) else None
                except Exception:
                    op.sla_state = None
                
                SLA_LABELS = {
                    SLAState.ON_TIME.value: "No prazo",
                    SLAState.AT_RISK.value: "Atenção",
                    SLAState.DELAYED.value: "Atrasado",
                    SLAState.COMPLETED_ON_TIME.value: "Concluído",
                    SLAState.COMPLETED_LATE.value: "Concluído",
                    SLAState.UNKNOWN.value: "-",
                }
                SLA_BADGE_CLASSES = {
                    SLAState.ON_TIME.value: "badge-success",
                    SLAState.AT_RISK.value: "badge-warning",
                    SLAState.DELAYED.value: "badge-danger",
                    SLAState.COMPLETED_ON_TIME.value: "badge-success light",
                    SLAState.COMPLETED_LATE.value: "badge-success light",
                    SLAState.UNKNOWN.value: "badge-light",
                }
                op.sla_display = SLA_LABELS.get(op.sla_state, "-")
                op.sla_badge_class = SLA_BADGE_CLASSES.get(op.sla_state, "badge-light")
        
        return context


class FreightOperationDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/freight_operations/detail.html"
    context_object_name = "operation"
    permission_code = PermissionCode.FREIGHT_OPERATIONS_VIEW
    active_menu = "freight_operations"
    page_title = "Detalhe da Operação"

    def get_queryset(self) -> QuerySet:
        return scoped_freight_operations_queryset(self.request.user, self.permission_code).select_related(
            "driver",
            "vehicle",
            "organization",
            "selection__offer__freight_request",
            "selection__offer__freight_request__customer",
        )

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
        user = self.request.user
        
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
        pods = list(ProofOfDelivery.objects.filter(operation=operation))
        context["pods"] = pods
        context["operation_pod"] = next((p for p in pods if p.stop_id is None), None)
        
        context["can_record_pod"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OPERATIONS_RECORD_POD
        )
        
        context["status_labels"] = STATUS_LABELS
        context["status_badge_classes"] = STATUS_BADGE_CLASSES
        
        events = list(operation.events.all().select_related("actor").order_by("created_at"))
        context["events"] = events
        context["incidents"] = [e for e in events if e.event_type == "INCIDENT_REPORTED"]
        
        if operation.stops.exists():
            stops = list(operation.stops.all().order_by("sequence"))
        elif (operation.selection and
              operation.selection.offer and
              operation.selection.offer.freight_request and
              hasattr(operation.selection.offer.freight_request, 'stops')):
            stops = list(operation.selection.offer.freight_request.stops.all().order_by("sequence"))
        else:
            stops = []
            
        pods_by_stop = {pod.stop_id: pod for pod in pods if pod.stop_id}
        for stop in stops:
            stop.pod = pods_by_stop.get(stop.id)
        context["stops"] = stops

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

        # Load intelligence details
        from src.intelligence.application.query_services import OperationIntelligenceQueryService
        from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
        repo = DjangoIntelligenceSnapshotRepository()
        query_service = OperationIntelligenceQueryService(repo)
        
        try:
            latest_intel = query_service.get_latest_assessment(
                operation_id=str(operation.id),
                organization_id=str(operation.organization.id),
                actor=user
            )
            history_intel = query_service.get_assessment_history(
                operation_id=str(operation.id),
                organization_id=str(operation.organization.id),
                actor=user
            )
        except Exception:
            latest_intel = None
            history_intel = []
            
        context["latest_intelligence"] = latest_intel
        context["intelligence_history"] = history_intel
        
        context["contracted_route"] = None
        if operation.source_type == "CONTRACTED_ROUTE" and hasattr(operation, "occurrence") and operation.occurrence:
            context["contracted_route"] = operation.occurrence.contracted_route
            
        return context


class FreightOperationAdvanceStatusView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS
    http_method_names = ["post"]

    def post(self, request, pk):
        operation = get_object_or_404(
            scoped_freight_operations_queryset(request.user, self.permission_code.value),
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
            scoped_freight_operations_queryset(request.user, self.permission_code.value),
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
            scoped_freight_operations_queryset(request.user, self.permission_code.value),
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
            scoped_freight_operations_queryset(request.user, self.permission_code.value),
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

        stop_id = request.POST.get("stop_id") or None
        try:
            record_proof_of_delivery(
                operation_id=operation.id,
                receiver_name=receiver_name,
                delivered_at=delivered_at,
                notes=notes,
                actor=request.user,
                stop_id=stop_id,
            )
            messages.success(request, "Proof of Delivery (POD) registrado com sucesso.")
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else str(e)
            messages.error(request, f"Erro ao registrar POD: {msg}")
        except Exception as e:
            messages.error(request, f"Erro inesperado: {str(e)}")

        return redirect("backoffice:freight_operation_detail", pk=pk)
