from django.db.models import Count, Q
from src.identity.domain.enums import PermissionCode
from src.freights.domain.enums import ThermalExcursionStatus, ThermalExcursionDirection
from src.freights.infrastructure.django.models import ThermalExcursion, ThermalReading
from src.shared.interfaces.backoffice.authorization import scoped_freight_operations_queryset
from src.freights.application.reporting.base_report import apply_operation_filters

def get_thermal_report(user, filters):
    ops = scoped_freight_operations_queryset(user, PermissionCode.FREIGHT_OPERATIONS_VIEW)
    ops = apply_operation_filters(ops, filters)
    
    # Filter refrigerated operations (which have temperature limits)
    refrig_ops = ops.filter(selection__offer__freight_request__cargo__temperature_min_c__isnull=False)
    
    # Operations with at least one thermal reading
    monitored_count = refrig_ops.annotate(
        readings_count=Count("thermal_readings")
    ).filter(readings_count__gt=0).count()
    
    readings_count = ThermalReading.objects.filter(operation__in=ops).count()
    
    excursions = ThermalExcursion.objects.filter(operation__in=ops)
    
    open_excursions = excursions.filter(status=ThermalExcursionStatus.ACTIVE.value).count()
    resolved_excursions = excursions.filter(status=ThermalExcursionStatus.RESOLVED.value).count()
    
    above_max = excursions.filter(direction=ThermalExcursionDirection.ABOVE_MAX.value).count()
    below_min = excursions.filter(direction=ThermalExcursionDirection.BELOW_MIN.value).count()
    
    # Get all excursions for table
    table_excursions = excursions.select_related(
        "operation__selection__offer__freight_request__cargo",
        "operation__vehicle",
    ).order_by("-started_at")
    
    charts = [
        {
            "id": "excursions_by_direction",
            "library": "apex",
            "type": "donut",
            "series": [above_max, below_min],
            "labels": ["Acima do Máximo (ABOVE_MAX)", "Abaixo do Mínimo (BELOW_MIN)"],
        }
    ]
    
    return {
        "kpis": {
            "refrigerated_operations": refrig_ops.count(),
            "monitored_operations": monitored_count,
            "thermal_readings": readings_count,
            "open_excursions": open_excursions,
            "resolved_excursions": resolved_excursions,
            "above_max": above_max,
            "below_min": below_min,
        },
        "charts": charts,
        "table_data": table_excursions,
    }
