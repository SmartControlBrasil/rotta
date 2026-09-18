from django.urls import path
from src.shared.interfaces.api.v1 import views

app_name = "api_v1"

urlpatterns = [
    # Auth
    path("auth/token/", views.login_view, name="login"),
    path("auth/token/refresh/", views.token_refresh_view, name="token_refresh"),
    path("auth/token/revoke/", views.token_revoke_view, name="token_revoke"),
    path("me/", views.me_view, name="me"),

    # Driver Preferences & Route Intents
    path("driver/preferences/", views.driver_preferences_view, name="driver_preferences"),
    path("driver/route-intents/", views.driver_route_intents_view, name="driver_route_intents"),
    path("driver/route-intents/<uuid:uuid>/cancel/", views.cancel_driver_route_intent_view, name="cancel_driver_route_intent"),
    
    # Operations
    path("driver/operations/", views.driver_operations_view, name="driver_operations"),
    path("driver/operations/<uuid:uuid>/", views.driver_operation_detail_view, name="driver_operation_detail"),
    path("driver/operations/<uuid:uuid>/advance-status/", views.advance_operation_status_view, name="advance_operation_status"),
    path("driver/operations/<uuid:uuid>/stops/<uuid:stop_uuid>/advance-status/", views.advance_stop_status_view, name="advance_stop_status"),
    path("driver/operations/<uuid:uuid>/incidents/", views.report_incident_view, name="report_incident"),
    path("driver/operations/<uuid:uuid>/pod/", views.record_pod_view, name="record_pod"),
    path("driver/operations/<uuid:uuid>/thermal-readings/", views.record_thermal_reading_view, name="record_thermal_reading"),
    
    # Tracking
    path("driver/operations/<uuid:uuid>/tracking/start/", views.start_tracking_view, name="start_tracking"),
    path("tracking/<uuid:session_uuid>/locations/", views.record_location_view, name="record_location"),
    path("tracking/<uuid:session_uuid>/locations/batch/", views.record_location_batch_view, name="record_location_batch"),
    path("tracking/<uuid:session_uuid>/end/", views.end_tracking_view, name="end_tracking"),

    # Customer Freight Requests
    path("customer/freight-requests/", views.customer_freight_requests_view, name="customer_freight_requests"),
    path("customer/freight-requests/<uuid:uuid>/", views.customer_freight_request_detail_view, name="customer_freight_request_detail"),
]
