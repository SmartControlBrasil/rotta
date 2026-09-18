from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDate
from datetime import timedelta

from src.shared.domain.enums import AccessScope
from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import OperationStatus, LoadType
from src.freights.infrastructure.django.models import ThermalExcursion
from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset
from src.freights.application.reporting.base_report import get_report_date_range, apply_operation_filters

def get_overview_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)

    total = ops.count()
    completed = ops.filter(status=OperationStatus.DELIVERED.value).count()
    cancelled = ops.filter(status=OperationStatus.CANCELLED.value).count()
    in_progress = total - completed - cancelled

    # SLA & delays
    from src.freights.application.sla_service import SLAService, SLAState
    on_time = 0
    delayed = 0
    # Prefetch relations to prevent N+1 queries during SLA computation
    ops_sla = ops.filter(status=OperationStatus.DELIVERED.value).select_related(
        "selection__offer__freight_request__cargo",
    ).prefetch_related(
        "stops",
    )
    for op in ops_sla:
        sla_res = SLAService.compute(op)
        if sla_res.state in (SLAState.ON_TIME, SLAState.COMPLETED_ON_TIME):
            on_time += 1
        elif sla_res.state in (SLAState.DELAYED, SLAState.COMPLETED_LATE):
            delayed += 1

    on_time_pct = (on_time / completed * 100) if completed > 0 else 100.0

    # Incident events and active drivers/carriers/vehicles
    incidents_total = 0
    pods_completed = 0

    # Prefetch events and pod to prevent N+1
    ops_details = ops.prefetch_related("events", "pods")
    for op in ops_details:
        incidents_total += op.events.filter(event_type="INCIDENT_REPORTED").count()
        if op.status == OperationStatus.DELIVERED.value and hasattr(op, 'pod') and op.pod:
            pods_completed += 1

    carriers_active = ops.values("carrier").distinct().count()
    drivers_active = ops.exclude(driver__isnull=True).values("driver").distinct().count()
    vehicles_used = ops.exclude(vehicle__isnull=True).values("vehicle").distinct().count()

    refrigerated = ops.filter(selection__offer__freight_request__cargo__temperature_min_c__isnull=False).count()
    excursions_total = ThermalExcursion.objects.filter(operation__in=ops).count()

    ftl = ops.filter(load_type=LoadType.FTL.value).count()
    ltl = ops.filter(load_type=LoadType.LTL.value).count()

    # Activity Chart
    start_dt, end_dt = get_report_date_range(filters)
    daily_ops = ops.annotate(date=TruncDate("created_at")).values("date").annotate(count=Count("id")).order_by("date")

    dates_labels = []
    counts_data = []
    curr = start_dt.date()
    while curr <= end_dt.date():
        dates_labels.append(curr.strftime("%d/%m"))
        match = next((x["count"] for x in daily_ops if x["date"] == curr), 0)
        counts_data.append(match)
        curr += timedelta(days=1)

    charts = [
        {
            "id": "overview_activity",
            "library": "apex",
            "type": "line",
            "categories": dates_labels,
            "series": [
                {"name": "Operações", "data": counts_data}
            ]
        }
    ]

    return {
        "kpis": {
            "operations_total": total,
            "operations_completed": completed,
            "operations_in_progress": in_progress,
            "operations_cancelled": cancelled,
            "on_time_percentage": round(on_time_pct, 1),
            "operations_delayed": delayed,
            "incidents_total": incidents_total,
            "pods_completed": pods_completed,
            "carriers_active": carriers_active,
            "drivers_active": drivers_active,
            "vehicles_used": vehicles_used,
            "refrigerated_monitored": refrigerated,
            "excursions_total": excursions_total,
            "ftl_total": ftl,
            "ltl_total": ltl,
        },
        "charts": charts,
    }

def get_operations_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)

    total = ops.count()
    completed = ops.filter(status=OperationStatus.DELIVERED.value).count()
    in_transit = ops.exclude(status__in=[OperationStatus.DELIVERED.value, OperationStatus.ASSIGNED.value, OperationStatus.CANCELLED.value]).count()
    cancelled = ops.filter(status=OperationStatus.CANCELLED.value).count()

    total_val = ops.aggregate(total=Sum("selection__offer__offer_amount"))["total"] or 0
    total_weight = ops.aggregate(total=Sum("selection__offer__freight_request__cargo__weight_kg"))["total"] or 0
    total_vol = ops.aggregate(total=Sum("selection__offer__freight_request__cargo__volume_m3"))["total"] or 0

    # Charts: status distribution & load types distribution
    status_counts = ops.values("status").annotate(count=Count("id"))
    status_series = [x["count"] for x in status_counts]
    status_labels = [x["status"] for x in status_counts]

    # Tabela: prefetch relations
    table_ops = ops.select_related(
        "carrier", "driver", "vehicle",
        "selection__offer__freight_request__cargo",
    ).prefetch_related(
        "stops",
    ).order_by("-created_at")

    # Limit table rows to 100 for display (can export all in CSV)
    return {
        "kpis": {
            "total_ops": total,
            "completed": completed,
            "in_transit": in_transit,
            "cancelled": cancelled,
            "total_value": float(total_val),
            "total_weight": float(total_weight),
            "total_volume": float(total_vol),
        },
        "charts": [
            {
                "id": "ops_by_status",
                "library": "apex",
                "type": "donut",
                "series": status_series,
                "labels": status_labels,
            }
        ],
        "table_data": table_ops[:100],
        "all_table_data": table_ops,
    }

def get_ftl_ltl_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)

    total = ops.count()
    ftl = ops.filter(load_type=LoadType.FTL.value).count()
    ltl = ops.filter(load_type=LoadType.LTL.value).count()
    not_informed = ops.filter(load_type__isnull=True).count()

    ftl_pct = (ftl / total * 100) if total > 0 else 0
    ltl_pct = (ltl / total * 100) if total > 0 else 0
    not_informed_pct = (not_informed / total * 100) if total > 0 else 0

    # SLA metrics for FTL/LTL
    from src.freights.application.sla_service import SLAService, SLAState

    def get_sla_stats(filtered_ops):
        completed_ops = filtered_ops.filter(status=OperationStatus.DELIVERED.value).select_related(
            "selection__offer__freight_request__cargo",
        ).prefetch_related(
            "stops",
        )
        total_completed = completed_ops.count()
        if total_completed == 0:
            return 100.0, 0
        on_time = 0
        for op in completed_ops:
            sla_res = SLAService.compute(op)
            if sla_res.state in (SLAState.ON_TIME, SLAState.COMPLETED_ON_TIME):
                on_time += 1
        return round(on_time / total_completed * 100, 1), total_completed

    ftl_sla_pct, ftl_completed = get_sla_stats(ops.filter(load_type=LoadType.FTL.value))
    ltl_sla_pct, ltl_completed = get_sla_stats(ops.filter(load_type=LoadType.LTL.value))

    charts = [
        {
            "id": "load_type_mix",
            "library": "apex",
            "type": "donut",
            "series": [ftl, ltl, not_informed],
            "labels": ["FTL", "LTL", "Não informado"],
        }
    ]

    return {
        "kpis": {
            "total": total,
            "ftl": ftl,
            "ltl": ltl,
            "not_informed": not_informed,
            "ftl_percentage": round(ftl_pct, 1),
            "ltl_percentage": round(ltl_pct, 1),
            "not_informed_percentage": round(not_informed_pct, 1),
            "ftl_sla_percentage": ftl_sla_pct,
            "ltl_sla_percentage": ltl_sla_pct,
        },
        "charts": charts,
    }
