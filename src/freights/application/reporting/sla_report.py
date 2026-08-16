from django.db.models import Avg, Max
from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import OperationStatus
from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset
from src.freights.application.reporting.base_report import apply_operation_filters
from src.freights.application.sla_service import SLAService, SLAState

def get_sla_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)
    
    # Calculate avg and max delay from database delay_minutes
    delays = ops.exclude(delay_minutes__isnull=True).aggregate(
        avg_delay=Avg("delay_minutes"),
        max_delay=Max("delay_minutes")
    )
    avg_delay_val = delays["avg_delay"] or 0.0
    max_delay_val = delays["max_delay"] or 0
    
    # SLA state counts for completed operations
    completed_ops = ops.filter(status=OperationStatus.DELIVERED.value).select_related(
        "selection__offer__freight_request__cargo"
    ).prefetch_related(
        "selection__offer__freight_request__stops"
    )
    
    on_time = 0
    late = 0
    at_risk = 0
    unknown = 0
    
    for op in completed_ops:
        sla_res = SLAService.compute(op)
        if sla_res.state in (SLAState.ON_TIME, SLAState.COMPLETED_ON_TIME):
            on_time += 1
        elif sla_res.state in (SLAState.DELAYED, SLAState.COMPLETED_LATE):
            late += 1
        elif sla_res.state == SLAState.AT_RISK:
            at_risk += 1
        else:
            unknown += 1
            
    total_completed = completed_ops.count()
    on_time_pct = (on_time / total_completed * 100) if total_completed > 0 else 100.0
    late_pct = (late / total_completed * 100) if total_completed > 0 else 0.0
    
    charts = [
        {
            "id": "sla_mix",
            "library": "apex",
            "type": "donut",
            "series": [on_time, late, at_risk, unknown],
            "labels": ["No Prazo", "Atrasado", "Em Risco", "Não Calculável"],
        }
    ]
    
    return {
        "kpis": {
            "total_completed": total_completed,
            "on_time": on_time,
            "late": late,
            "at_risk": at_risk,
            "unknown": unknown,
            "on_time_percentage": round(on_time_pct, 1),
            "late_percentage": round(late_pct, 1),
            "avg_delay_minutes": round(avg_delay_val, 1),
            "max_delay_minutes": max_delay_val,
        },
        "charts": charts,
    }
