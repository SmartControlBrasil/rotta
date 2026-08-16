from django.db.models import Count, Sum, Q
from src.identity.domain.enums import PermissionCode
from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset, scoped_vehicle_queryset
from src.freights.application.reporting.base_report import apply_operation_filters

def get_fleet_report(user, filters):
    vehicles = scoped_vehicle_queryset(user, PermissionCode.VEHICLES_VIEW)
    
    # Apply organization filter on vehicles if provided
    org_id = filters.get("organization_id")
    if org_id:
        vehicles = vehicles.filter(organization_id=org_id)
        
    total_vehicles = vehicles.count()
    active_vehicles = vehicles.filter(status="ACTIVE").count()
    
    # Calculate vehicle utilisation in operations
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)
    
    used_vehicles = ops.exclude(vehicle__isnull=True).values("vehicle").distinct().count()
    
    # Detailed vehicle usage stats (without N+1)
    vehicle_usage = ops.exclude(vehicle__isnull=True).values(
        "vehicle__id", "vehicle__plate", "vehicle__capacity_weight_kg", "vehicle__status"
    ).annotate(
        ops_count=Count("id"),
        dry_ops=Count("id", filter=Q(selection__offer__freight_request__cargo__cargo_profile="DRY_CARGO")),
        refrigerated_ops=Count("id", filter=Q(selection__offer__freight_request__cargo__cargo_profile="REFRIGERATED")),
        weight_sum=Sum("selection__offer__freight_request__cargo__weight_kg"),
    ).order_by("-ops_count")
    
    table_data = []
    for vu in vehicle_usage:
        table_data.append({
            "id": vu["vehicle__id"],
            "plate": vu["vehicle__plate"],
            "capacity": float(vu["vehicle__capacity_weight_kg"] or 0),
            "ops_count": vu["ops_count"],
            "dry_ops": vu["dry_ops"],
            "refrigerated_ops": vu["refrigerated_ops"],
            "weight_kg": float(vu["weight_sum"] or 0),
            "status": vu["vehicle__status"],
        })
        
    return {
        "kpis": {
            "total_vehicles": total_vehicles,
            "active_vehicles": active_vehicles,
            "used_vehicles": used_vehicles,
        },
        "table_data": table_data,
    }
