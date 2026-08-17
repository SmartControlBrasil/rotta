from django.urls import path
from . import views

app_name = "customer"

urlpatterns = [
    path("", views.CustomerDashboardView.as_view(), name="dashboard"),
    path("freight-requests/", views.CustomerFreightRequestListView.as_view(), name="freight_requests_list"),
    path("freight-requests/new/", views.CustomerFreightRequestCreateView.as_view(), name="freight_requests_new"),
    path("freight-requests/<uuid:uuid>/", views.CustomerFreightRequestDetailView.as_view(), name="freight_request_detail"),
]
