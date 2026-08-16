import csv
from django.http import StreamingHttpResponse
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import OperationStatus, LoadType, FreightCargoProfile
from src.shared.interfaces.backoffice.views import BackofficePermissionMixin, BackofficeContextMixin
from src.shared.interfaces.backoffice.authorization import (
    scoped_organization_queryset,
    scoped_carrier_queryset,
    scoped_driver_queryset,
    scoped_vehicle_queryset,
    scoped_freight_operations_queryset,
)
from src.freights.application.reporting.operations_report import (
    get_overview_report,
    get_operations_report,
    get_ftl_ltl_report,
)
from src.freights.application.reporting.marketplace_report import get_marketplace_report
from src.freights.application.reporting.people_report import get_carriers_report, get_drivers_report
from src.freights.application.reporting.fleet_report import get_fleet_report
from src.freights.application.reporting.sla_report import get_sla_report
from src.freights.application.reporting.thermal_report import get_thermal_report

class Echo:
    def write(self, value):
        return value

def generate_csv_response(filename, headers, rows):
    pseudo_buffer = Echo()
    writer = csv.writer(pseudo_buffer)
    
    def generator():
        yield writer.writerow(headers)
        for row in rows:
            yield writer.writerow(row)
            
    response = StreamingHttpResponse(generator(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class ReportBaseView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    login_url = reverse_lazy("backoffice:login")
    permission_code = PermissionCode.REPORTS_VIEW
    active_menu = "reports"
    report_key = "overview"
    
    def get_breadcrumbs(self):
        return (
            ("Relatórios", None),
            (self.page_title, None),
        )
        
    def get_filters(self):
        filters = {}
        for key in ["start_date", "end_date", "organization_id", "carrier_id", "driver_id", "vehicle_id", "status", "cargo_profile", "load_type"]:
            val = self.request.GET.get(key)
            if val:
                filters[key] = val
        return filters

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.get_filters()
        context["filters"] = filters
        context["report_key"] = self.report_key
        
        # Scope filters
        context["organizations"] = scoped_organization_queryset(self.request.user, PermissionCode.ORGANIZATIONS_VIEW)
        context["carriers"] = scoped_carrier_queryset(self.request.user, PermissionCode.CARRIERS_VIEW)
        context["drivers"] = scoped_driver_queryset(self.request.user, PermissionCode.DRIVERS_VIEW)
        context["vehicles"] = scoped_vehicle_queryset(self.request.user, PermissionCode.VEHICLES_VIEW)
        context["statuses"] = [s.value for s in OperationStatus]
        context["load_types"] = [lt.value for lt in LoadType]
        context["cargo_profiles"] = [p.value for p in FreightCargoProfile]
        
        return context


class ReportOverviewView(ReportBaseView):
    template_name = "backoffice/pages/reports/overview.html"
    page_title = "Visão Geral"
    report_key = "overview"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_overview_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["chart_payload"] = {"charts": data["charts"]}
        return context


class ReportOperationsView(ReportBaseView):
    template_name = "backoffice/pages/reports/operations.html"
    page_title = "Operações e Fretes"
    report_key = "operations"

    def get(self, request, *args, **kwargs):
        filters = self.get_filters()
        data = get_operations_report(request.user, filters)
        
        if request.GET.get("export") == "csv":
            headers = ["Referência", "Data", "Organização", "Transportadora", "Motorista", "Veículo", "Status", "Tipo de Carga", "FTL/LTL", "Valor (BRL)"]
            rows = []
            for op in data["all_table_data"]:
                offer = op.selection.offer
                req = offer.freight_request
                cargo = getattr(req, "cargo", None)
                rows.append([
                    offer.reference_code,
                    op.created_at.strftime("%d/%m/%Y"),
                    op.organization.name,
                    op.carrier.trade_name,
                    op.driver.full_name if op.driver else "N/A",
                    op.vehicle.plate if op.vehicle else "N/A",
                    op.status,
                    cargo.cargo_profile if cargo else "N/A",
                    op.load_type or "Não informado",
                    offer.offer_amount,
                ])
            return generate_csv_response("operacoes_fretes.csv", headers, rows)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_operations_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["chart_payload"] = {"charts": data["charts"]}
        context["table_data"] = data["table_data"]
        return context


class ReportMarketplaceView(ReportBaseView):
    template_name = "backoffice/pages/reports/marketplace.html"
    page_title = "Marketplace"
    report_key = "marketplace"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_marketplace_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["chart_payload"] = {"charts": data["charts"]}
        return context


class ReportCarriersView(ReportBaseView):
    template_name = "backoffice/pages/reports/carriers.html"
    page_title = "Transportadoras"
    report_key = "carriers"

    def get(self, request, *args, **kwargs):
        filters = self.get_filters()
        data = get_carriers_report(request.user, filters)
        
        if request.GET.get("export") == "csv":
            headers = ["Transportadora", "Operações Atribuídas", "Concluídas", "SLA (%)", "Incidentes", "Peso Transportado (kg)", "Volume (m3)"]
            rows = []
            for c in data["table_data"]:
                rows.append([
                    c["trade_name"],
                    c["ops_count"],
                    c["completed_count"],
                    c["sla_percentage"],
                    c["incidents"],
                    c["weight_kg"],
                    c["volume_m3"],
                ])
            return generate_csv_response("transportadoras_performance.csv", headers, rows)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_carriers_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["table_data"] = data["table_data"]
        return context


class ReportDriversView(ReportBaseView):
    template_name = "backoffice/pages/reports/drivers.html"
    page_title = "Motoristas"
    report_key = "drivers"

    def get(self, request, *args, **kwargs):
        filters = self.get_filters()
        data = get_drivers_report(request.user, filters)
        
        if request.GET.get("export") == "csv":
            headers = ["Motorista", "Operações Atribuídas", "Concluídas", "Cancelamentos", "SLA (%)", "Incidentes", "PODs Entregues"]
            rows = []
            for d in data["table_data"]:
                rows.append([
                    d["full_name"],
                    d["ops_count"],
                    d["completed_count"],
                    d["cancelled_count"],
                    d["sla_percentage"],
                    d["incidents"],
                    d["pods"],
                ])
            return generate_csv_response("motoristas_performance.csv", headers, rows)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_drivers_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["table_data"] = data["table_data"]
        return context


class ReportFleetView(ReportBaseView):
    template_name = "backoffice/pages/reports/fleet.html"
    page_title = "Frota"
    report_key = "fleet"

    def get(self, request, *args, **kwargs):
        filters = self.get_filters()
        data = get_fleet_report(request.user, filters)
        
        if request.GET.get("export") == "csv":
            headers = ["Placa", "Capacidade Peso (kg)", "Status Veículo", "Operações Totais", "Carga Seca", "Carga Refrigerada", "Peso Total Transportado (kg)"]
            rows = []
            for v in data["table_data"]:
                rows.append([
                    v["plate"],
                    v["capacity"],
                    v["status"],
                    v["ops_count"],
                    v["dry_ops"],
                    v["refrigerated_ops"],
                    v["weight_kg"],
                ])
            return generate_csv_response("frota_utilizacao.csv", headers, rows)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_fleet_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["table_data"] = data["table_data"]
        return context


class ReportSLAView(ReportBaseView):
    template_name = "backoffice/pages/reports/sla.html"
    page_title = "SLA e Atrasos"
    report_key = "sla"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_sla_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["chart_payload"] = {"charts": data["charts"]}
        return context


class ReportIncidentsView(ReportBaseView):
    template_name = "backoffice/pages/reports/incidents.html"
    page_title = "Incidentes e POD"
    report_key = "incidents"

    def get(self, request, *args, **kwargs):
        from src.freights.application.reporting.base_report import apply_operation_filters
        from src.freights.infrastructure.django.models import FreightOperationEvent
        
        ops = scoped_freight_operations_queryset(request.user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
        ops = apply_operation_filters(ops, self.get_filters())
        
        # Get incident events
        incidents = FreightOperationEvent.objects.filter(
            event_type="INCIDENT_REPORTED", operation__in=ops
        ).select_related("operation__selection__offer", "operation__carrier", "operation__driver").order_by("-occurred_at")
        
        # Get PODs
        pods = ops.filter(status=OperationStatus.DELIVERED.value).select_related("pod", "selection__offer", "carrier", "driver").exclude(pod__isnull=True).order_by("-completed_at")
        
        if request.GET.get("export") == "csv":
            headers = ["Operação", "Tipo de Registro", "Data/Hora", "Transportadora", "Motorista", "Detalhes"]
            rows = []
            for inc in incidents:
                rows.append([
                    inc.operation.selection.offer.reference_code,
                    "INCIDENTE",
                    inc.occurred_at.strftime("%d/%m/%Y %H:%M"),
                    inc.operation.carrier.trade_name,
                    inc.operation.driver.full_name if inc.operation.driver else "N/A",
                    inc.notes,
                ])
            for op in pods:
                pod = op.pod
                rows.append([
                    op.selection.offer.reference_code,
                    "POD_ENTREGA",
                    pod.delivered_at.strftime("%d/%m/%Y %H:%M"),
                    op.carrier.trade_name,
                    op.driver.full_name if op.driver else "N/A",
                    f"Recebedor: {pod.receiver_name}",
                ])
            return generate_csv_response("incidentes_pods.csv", headers, rows)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from src.freights.application.reporting.base_report import apply_operation_filters
        from src.freights.infrastructure.django.models import FreightOperationEvent
        
        ops = scoped_freight_operations_queryset(self.request.user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
        ops = apply_operation_filters(ops, context["filters"])
        
        incidents = FreightOperationEvent.objects.filter(
            event_type="INCIDENT_REPORTED", operation__in=ops
        ).select_related("operation__selection__offer", "operation__carrier", "operation__driver").order_by("-occurred_at")
        
        pods = ops.filter(status=OperationStatus.DELIVERED.value).select_related("pod", "selection__offer", "carrier", "driver").exclude(pod__isnull=True).order_by("-completed_at")
        
        context["kpis"] = {
            "incidents_count": incidents.count(),
            "pods_count": pods.count(),
        }
        context["incidents"] = incidents[:50]
        context["pods"] = pods[:50]
        return context


class ReportThermalView(ReportBaseView):
    template_name = "backoffice/pages/reports/thermal.html"
    page_title = "Carga Refrigerada"
    report_key = "thermal"

    def get(self, request, *args, **kwargs):
        filters = self.get_filters()
        data = get_thermal_report(request.user, filters)
        
        if request.GET.get("export") == "csv":
            headers = ["Operação", "Carga", "Veículo", "Sensor", "Início", "Fim", "Direção", "Min Obs", "Max Obs", "Status"]
            rows = []
            for ex in data["table_data"]:
                rows.append([
                    ex.operation.selection.offer.reference_code,
                    ex.operation.selection.offer.freight_request.cargo.description,
                    ex.operation.vehicle.plate if ex.operation.vehicle else "N/A",
                    ex.sensor_id,
                    ex.started_at.strftime("%d/%m/%Y %H:%M"),
                    ex.ended_at.strftime("%d/%m/%Y %H:%M") if ex.ended_at else "Ativo",
                    ex.direction,
                    ex.min_observed,
                    ex.max_observed,
                    ex.status,
                ])
            return generate_csv_response("carga_refrigerada_excursoes.csv", headers, rows)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_thermal_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["chart_payload"] = {"charts": data["charts"]}
        context["table_data"] = data["table_data"]
        return context


class ReportLoadTypesView(ReportBaseView):
    template_name = "backoffice/pages/reports/load_types.html"
    page_title = "FTL x LTL"
    report_key = "load_types"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = get_ftl_ltl_report(self.request.user, context["filters"])
        context["kpis"] = data["kpis"]
        context["chart_payload"] = {"charts": data["charts"]}
        return context
