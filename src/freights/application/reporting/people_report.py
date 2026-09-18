from django.db.models import Count, Sum, Q
from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import OperationStatus
from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset
from src.freights.application.reporting.base_report import apply_operation_filters
from src.freights.application.sla_service import SLAService, SLAState

def get_carriers_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)

    # Query aggregations grouped by carrier
    carrier_summary = ops.values(
        "carrier__id", "carrier__trade_name"
    ).annotate(
        ops_count=Count("id"),
        completed_count=Count("id", filter=Q(status=OperationStatus.DELIVERED.value)),
        weight_sum=Sum("selection__offer__freight_request__cargo__weight_kg"),
        volume_sum=Sum("selection__offer__freight_request__cargo__volume_m3"),
    ).order_by("-ops_count")

    # SLA calculation per carrier (without N+1)
    ops_completed = ops.filter(status=OperationStatus.DELIVERED.value).select_related(
        "carrier", "selection__offer__freight_request__cargo"
    ).prefetch_related(
        "stops"
    )

    carrier_sla = {} # carrier_id -> (on_time, total)
    for op in ops_completed:
        cid = op.carrier_id
        sla_res = SLAService.compute(op)
        on_time = sla_res.state in (SLAState.ON_TIME, SLAState.COMPLETED_ON_TIME)

        stats = carrier_sla.setdefault(cid, [0, 0])
        stats[1] += 1
        if on_time:
            stats[0] += 1

    # Calculate incidents count per carrier
    carrier_incidents = {}
    ops_details = ops.select_related("carrier").prefetch_related("events")
    for op in ops_details:
        incidents = op.events.filter(event_type="INCIDENT_REPORTED").count()
        if incidents > 0:
            cid = op.carrier_id
            carrier_incidents[cid] = carrier_incidents.get(cid, 0) + incidents

    carriers_data = []
    for c in carrier_summary:
        cid = c["carrier__id"]
        sla_stats = carrier_sla.get(cid, [0, 0])
        sla_pct = (sla_stats[0] / sla_stats[1] * 100) if sla_stats[1] > 0 else 100.0

        carriers_data.append({
            "id": cid,
            "trade_name": c["carrier__trade_name"],
            "ops_count": c["ops_count"],
            "completed_count": c["completed_count"],
            "sla_percentage": round(sla_pct, 1),
            "incidents": carrier_incidents.get(cid, 0),
            "weight_kg": float(c["weight_sum"] or 0),
            "volume_m3": float(c["volume_sum"] or 0),
        })

    return {
        "kpis": {
            "active_carriers": len(carriers_data),
        },
        "table_data": carriers_data,
    }

def get_drivers_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)

    # Query aggregations grouped by driver
    driver_summary = ops.exclude(driver__isnull=True).values(
        "driver__id", "driver__full_name"
    ).annotate(
        ops_count=Count("id"),
        completed_count=Count("id", filter=Q(status=OperationStatus.DELIVERED.value)),
        cancelled_count=Count("id", filter=Q(status=OperationStatus.CANCELLED.value)),
    ).order_by("-ops_count")

    # SLA calculation per driver (without N+1)
    ops_completed = ops.filter(status=OperationStatus.DELIVERED.value).select_related(
        "driver", "selection__offer__freight_request__cargo"
    ).prefetch_related(
        "stops"
    )

    driver_sla = {}
    for op in ops_completed:
        did = op.driver_id
        if did:
            sla_res = SLAService.compute(op)
            on_time = sla_res.state in (SLAState.ON_TIME, SLAState.COMPLETED_ON_TIME)
            stats = driver_sla.setdefault(did, [0, 0])
            stats[1] += 1
            if on_time:
                stats[0] += 1

    # Calculate incidents and PODs per driver
    driver_incidents = {}
    driver_pods = {}
    ops_details = ops.exclude(driver__isnull=True).select_related("driver").prefetch_related("events", "pods")
    for op in ops_details:
        did = op.driver_id
        incidents = op.events.filter(event_type="INCIDENT_REPORTED").count()
        if incidents > 0:
            driver_incidents[did] = driver_incidents.get(did, 0) + incidents
        if op.status == OperationStatus.DELIVERED.value and hasattr(op, 'pod') and op.pod:
            driver_pods[did] = driver_pods.get(did, 0) + 1

    drivers_data = []
    for d in driver_summary:
        did = d["driver__id"]
        sla_stats = driver_sla.get(did, [0, 0])
        sla_pct = (sla_stats[0] / sla_stats[1] * 100) if sla_stats[1] > 0 else 100.0

        drivers_data.append({
            "id": did,
            "full_name": d["driver__full_name"],
            "ops_count": d["ops_count"],
            "completed_count": d["completed_count"],
            "cancelled_count": d["cancelled_count"],
            "sla_percentage": round(sla_pct, 1),
            "incidents": driver_incidents.get(did, 0),
            "pods": driver_pods.get(did, 0),
        })

    return {
        "kpis": {
            "active_drivers": len(drivers_data),
        },
        "table_data": drivers_data,
    }
