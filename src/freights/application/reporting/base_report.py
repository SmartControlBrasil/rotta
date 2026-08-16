from datetime import timedelta, date, datetime
from django.utils import timezone
from src.freights.domain.enums import OperationStatus, LoadType

def get_report_date_range(filters):
    start_date_str = filters.get("start_date")
    end_date_str = filters.get("end_date")
    
    end_dt = timezone.now()
    start_dt = end_dt - timedelta(days=30)
    
    if start_date_str:
        try:
            start_dt = timezone.make_aware(datetime.combine(date.fromisoformat(start_date_str), datetime.min.time()))
        except ValueError:
            pass
    if end_date_str:
        try:
            end_dt = timezone.make_aware(datetime.combine(date.fromisoformat(end_date_str), datetime.max.time()))
        except ValueError:
            pass
            
    return start_dt, end_dt

def apply_operation_filters(qs, filters):
    # Apply period
    start_dt, end_dt = get_report_date_range(filters)
    qs = qs.filter(created_at__range=(start_dt, end_dt))
    
    # Filter by organization
    org_id = filters.get("organization_id")
    if org_id:
        qs = qs.filter(organization_id=org_id)
        
    # Filter by carrier
    carrier_id = filters.get("carrier_id")
    if carrier_id:
        qs = qs.filter(carrier_id=carrier_id)
        
    # Filter by driver
    driver_id = filters.get("driver_id")
    if driver_id:
        qs = qs.filter(driver_id=driver_id)
        
    # Filter by vehicle
    vehicle_id = filters.get("vehicle_id")
    if vehicle_id:
        qs = qs.filter(vehicle_id=vehicle_id)
        
    # Filter by status
    status = filters.get("status")
    if status:
        qs = qs.filter(status=status)
        
    # Filter by cargo profile (e.g. DRY_CARGO, REFRIGERATED)
    cargo_profile = filters.get("cargo_profile")
    if cargo_profile:
        qs = qs.filter(selection__offer__freight_request__cargo__cargo_profile=cargo_profile)
        
    # Filter by load type
    load_type = filters.get("load_type")
    if load_type:
        if load_type == "NULL":
            qs = qs.filter(load_type__isnull=True)
        else:
            qs = qs.filter(load_type=load_type)
            
    return qs
