from datetime import timedelta

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models as django_models
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import defaults as default_views
from django.views.generic import DetailView, ListView, TemplateView

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.application.services import (
    CarrierData,
    change_carrier_status,
    create_carrier,
    update_carrier,
)
from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus
from src.carriers.infrastructure.django.models import CarrierProfile
from src.compliance.application.evaluation import evaluate_entity_compliance
from src.compliance.application.expiration import expiration_window_filter, expired_filter
from src.compliance.application.queries import document_kpis
from src.compliance.domain.enums import ComplianceStatus, DocumentStatus, EntityType
from src.customers.application.services import (
    CustomerData,
    change_customer_status,
    register_customer,
    update_customer,
)
from src.customers.domain.enums import CustomerStatus, CustomerType
from src.customers.infrastructure.django.models import Customer
from src.drivers.application.services import (
    DriverData,
    approve_driver,
    change_driver_status,
    register_driver,
    start_driver_review,
    suspend_driver,
    update_driver,
)
from src.drivers.domain.enums import (
    DriverApprovalStatus,
    DriverAvailabilityStatus,
    DriverEngagementType,
    DriverLicenseCategory,
    DriverStatus,
)
from src.drivers.infrastructure.django.models import Driver
from src.freights.domain.enums import FreightCargoProfile, FreightRequestStatus
from src.freights.domain.offer_enums import FreightOfferStatus
from src.freights.domain.quote_enums import FreightQuoteStatus
from src.freights.infrastructure.django.models import FreightOffer, FreightQuote, FreightRequest
from src.identity.application.services import (
    create_user_with_membership,
    update_user_details,
    update_user_membership,
)
from src.identity.domain.enums import PermissionCode
from src.identity.infrastructure.django.models import MembershipRole, Permission, Role
from src.organizations.application.services import (
    create_branch,
    create_business_unit,
    create_department,
    create_organization,
    create_team,
    update_branch,
    update_business_unit,
    update_department,
    update_organization,
    update_team,
)
from src.organizations.infrastructure.django.models import (
    Branch,
    BusinessUnit,
    Department,
    Membership,
    Organization,
    Team,
)
from src.shared.domain.enums import AccessScope
from src.vehicles.application.services import (
    RefrigerationProfileData,
    VehicleData,
    change_vehicle_operational_status,
    change_vehicle_status,
    register_vehicle,
    update_vehicle,
    upsert_refrigeration_profile,
)
from src.vehicles.domain.enums import (
    RefrigerationControlType,
    VehicleBodyType,
    VehicleCargoProfile,
    VehicleDocumentType,
    VehicleOperationalStatus,
    VehicleStatus,
    VehicleType,
)
from src.vehicles.infrastructure.django.models import Vehicle

from .authorization import (
    permission_grant_for,
    scoped_branch_queryset,
    scoped_business_unit_queryset,
    scoped_carrier_document_queryset,
    scoped_carrier_queryset,
    scoped_customer_queryset,
    scoped_department_queryset,
    scoped_driver_document_queryset,
    scoped_driver_queryset,
    scoped_freight_offer_queryset,
    scoped_freight_quote_queryset,
    scoped_freight_request_queryset,
    scoped_membership_queryset,
    scoped_organization_queryset,
    scoped_team_queryset,
    scoped_user_queryset,
    scoped_vehicle_document_queryset,
    scoped_vehicle_queryset,
    user_has_backoffice_permission,
)

PAGE_SIZE = 25


class BackofficeContextMixin:
    active_menu = "dashboard"
    page_title = "Dashboard"
    breadcrumbs = ()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = getattr(self.request, "user", None)
        dashboard_menu = {
            "overview": bool(user and user.is_authenticated),
            "operations": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.DRIVERS_VIEW)
            ),
            "relationship": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.CUSTOMERS_VIEW)
            ),
            "finance": bool(
                user and user.is_authenticated and _has_permission(user, PermissionCode.AUDIT_VIEW)
            ),
            "analytics": bool(
                user and user.is_authenticated and _has_permission(user, PermissionCode.USERS_VIEW)
            ),
            "commercial": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.CUSTOMERS_VIEW)
            ),
            "marketplace": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.CARRIERS_VIEW)
            ),
            "compliance": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.COMPLIANCE_VIEW)
            ),
            "documents": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.DOCUMENTS_VIEW)
            ),
            "fleet_health": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.VEHICLES_VIEW)
            ),
            "freight_requests": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
            ),
            "freight_quotes": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.FREIGHT_QUOTES_VIEW)
            ),
            "freight_offers": bool(
                user
                and user.is_authenticated
                and _has_permission(user, PermissionCode.FREIGHT_OFFERS_VIEW)
            ),
        }
        context.update(
            active_menu=self.active_menu,
            page_title=self.page_title,
            breadcrumbs=self.get_breadcrumbs(),
            dashboard_menu=dashboard_menu,
        )
        return context

    def get_breadcrumbs(self):
        return self.breadcrumbs


class BackofficePermissionMixin(LoginRequiredMixin):
    login_url = reverse_lazy("backoffice:login")
    permission_code = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.permission_code and not user_has_backoffice_permission(
            request.user, self.permission_code
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def permission_grant(self):
        return permission_grant_for(self.request.user, self.permission_code)


class FilteredListView(BackofficePermissionMixin, BackofficeContextMixin, ListView):
    paginate_by = PAGE_SIZE

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = self.request.GET
        return context


class BackofficeDashboardView(LoginRequiredMixin, BackofficeContextMixin, TemplateView):
    """NexaDash dashboard backed by real Rotta foundation metrics."""

    template_name = "backoffice/dashboard.html"
    login_url = reverse_lazy("backoffice:login")
    active_menu = "dashboard"
    page_title = "Visão Geral"
    breadcrumbs = (("Dashboard", None), ("Visão Geral", None))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        metrics = []

        if user_has_backoffice_permission(user, PermissionCode.ORGANIZATIONS_VIEW):
            metrics.append(
                {
                    "label": "Organizations",
                    "value": scoped_organization_queryset(
                        user, PermissionCode.ORGANIZATIONS_VIEW
                    ).count(),
                    "url": reverse_lazy("backoffice:organizations"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.USERS_VIEW):
            metrics.append(
                {
                    "label": "Users",
                    "value": scoped_user_queryset(user, PermissionCode.USERS_VIEW).count(),
                    "url": reverse_lazy("backoffice:users"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.MEMBERSHIPS_VIEW):
            metrics.append(
                {
                    "label": "Memberships",
                    "value": scoped_membership_queryset(
                        user, PermissionCode.MEMBERSHIPS_VIEW
                    ).count(),
                    "url": reverse_lazy("backoffice:memberships"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.ROLES_MANAGE):
            metrics.append(
                {
                    "label": "Roles",
                    "value": Role.objects.count(),
                    "url": reverse_lazy("backoffice:roles"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.DRIVERS_VIEW):
            metrics.append(
                {
                    "label": "Motoristas",
                    "value": scoped_driver_queryset(user, PermissionCode.DRIVERS_VIEW).count(),
                    "url": reverse_lazy("backoffice:drivers"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.VEHICLES_VIEW):
            metrics.append(
                {
                    "label": "Veículos",
                    "value": scoped_vehicle_queryset(user, PermissionCode.VEHICLES_VIEW).count(),
                    "url": reverse_lazy("backoffice:vehicles"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.CUSTOMERS_VIEW):
            metrics.append(
                {
                    "label": "Clientes",
                    "value": scoped_customer_queryset(user, PermissionCode.CUSTOMERS_VIEW).count(),
                    "url": reverse_lazy("backoffice:customers"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.CARRIERS_VIEW):
            metrics.append(
                {
                    "label": "Transportadoras",
                    "value": scoped_carrier_queryset(user, PermissionCode.CARRIERS_VIEW).count(),
                    "url": reverse_lazy("backoffice:carriers"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.FREIGHT_REQUESTS_VIEW):
            open_statuses = [
                FreightRequestStatus.DRAFT.value,
                FreightRequestStatus.SUBMITTED.value,
                FreightRequestStatus.UNDER_REVIEW.value,
            ]
            metrics.append(
                {
                    "label": "Solicitações abertas",
                    "value": scoped_freight_request_queryset(
                        user, PermissionCode.FREIGHT_REQUESTS_VIEW
                    )
                    .filter(status__in=open_statuses)
                    .count(),
                    "url": reverse_lazy("backoffice:freight_requests"),
                }
            )
            metrics.append(
                {
                    "label": "Solicitações hoje",
                    "value": scoped_freight_request_queryset(
                        user, PermissionCode.FREIGHT_REQUESTS_VIEW
                    )
                    .filter(created_at__date=timezone.now().date())
                    .count(),
                    "url": reverse_lazy("backoffice:freight_requests"),
                }
            )
        if user_has_backoffice_permission(user, PermissionCode.AUDIT_VIEW):
            metrics.append(
                {
                    "label": "Audit logs",
                    "value": AuditLog.objects.count(),
                    "url": reverse_lazy("backoffice:audit"),
                }
            )

        audit_since = timezone.now() - timedelta(days=7)
        audit_by_day = []
        if user_has_backoffice_permission(user, PermissionCode.AUDIT_VIEW):
            audit_by_day = list(
                AuditLog.objects.filter(created_at__gte=audit_since)
                .extra(select={"day": "date(created_at)"})
                .values("day")
                .annotate(total=Count("id"))
                .order_by("day")
            )

        context["metrics"] = metrics
        context["recent_audit_logs"] = (
            AuditLog.objects.select_related("actor", "organization")[:8]
            if user_has_backoffice_permission(user, PermissionCode.AUDIT_VIEW)
            else []
        )
        context["audit_by_day"] = audit_by_day
        snapshot = _dashboard_snapshot(user)
        context["snapshot"] = snapshot
        context["chart_key"] = "overview"
        context["chart_payload"] = {
            "charts": [
                {
                    "id": "chartBar",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {
                            "name": "Clientes",
                            "data": [snapshot["customers_total"], snapshot["customers_active"]],
                        },
                        {
                            "name": "Transportadoras",
                            "data": [snapshot["carriers_total"], snapshot["carriers_active"]],
                        },
                    ],
                    "categories": ["Cadastrados", "Ativos"],
                },
                {
                    "id": "NewCustomers",
                    "library": "apex",
                    "type": "line",
                    "series": [
                        {"name": "Motoristas", "data": [snapshot["drivers_total"]] * 6},
                        {"name": "Veículos", "data": [snapshot["vehicles_total"]] * 6},
                    ],
                    "categories": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"],
                },
                {
                    "id": "pieChart1",
                    "library": "apex",
                    "type": "donut",
                    "series": [
                        snapshot["vehicles_dry"],
                        snapshot["vehicles_refrigerated"],
                        snapshot["vehicles_both"],
                    ],
                    "labels": ["Carga seca", "Refrigerada", "Ambas"],
                },
                {
                    "id": "chartTimeline",
                    "library": "apex",
                    "type": "area",
                    "series": [
                        {
                            "name": "Recursos ativos",
                            "data": [snapshot["drivers_active"] + snapshot["vehicles_active"]] * 7,
                        }
                    ],
                    "categories": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"],
                },
            ]
        }
        return context


def _has_permission(user, permission_code: str) -> bool:
    return user_has_backoffice_permission(user, permission_code)


def _dashboard_snapshot(user) -> dict[str, int]:
    customers_qs = (
        scoped_customer_queryset(user, PermissionCode.CUSTOMERS_VIEW)
        if _has_permission(user, PermissionCode.CUSTOMERS_VIEW)
        else Customer.objects.none()
    )
    carriers_qs = (
        scoped_carrier_queryset(user, PermissionCode.CARRIERS_VIEW)
        if _has_permission(user, PermissionCode.CARRIERS_VIEW)
        else CarrierProfile.objects.none()
    )
    drivers_qs = (
        scoped_driver_queryset(user, PermissionCode.DRIVERS_VIEW)
        if _has_permission(user, PermissionCode.DRIVERS_VIEW)
        else Driver.objects.none()
    )
    vehicles_qs = (
        scoped_vehicle_queryset(user, PermissionCode.VEHICLES_VIEW)
        if _has_permission(user, PermissionCode.VEHICLES_VIEW)
        else Vehicle.objects.none()
    )
    users_qs = (
        scoped_user_queryset(user, PermissionCode.USERS_VIEW)
        if _has_permission(user, PermissionCode.USERS_VIEW)
        else None
    )

    customer_stats = customers_qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=CustomerStatus.ACTIVE.value)),
        prospects=Count("id", filter=Q(status=CustomerStatus.PROSPECT.value)),
    )
    carrier_stats = carriers_qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=CarrierStatus.ACTIVE.value)),
        pending=Count("id", filter=Q(status=CarrierStatus.PENDING_APPROVAL.value)),
    )
    driver_stats = drivers_qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=DriverStatus.ACTIVE.value)),
        pending=Count("id", filter=Q(status=DriverStatus.PENDING.value)),
        blocked=Count("id", filter=Q(status=DriverStatus.BLOCKED.value)),
        available=Count(
            "id", filter=Q(availability_status=DriverAvailabilityStatus.AVAILABLE.value)
        ),
    )
    vehicle_stats = vehicles_qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=VehicleStatus.ACTIVE.value)),
        blocked=Count("id", filter=Q(status=VehicleStatus.BLOCKED.value)),
        maintenance=Count(
            "id", filter=Q(operational_status=VehicleOperationalStatus.MAINTENANCE.value)
        ),
        available=Count(
            "id", filter=Q(operational_status=VehicleOperationalStatus.AVAILABLE.value)
        ),
        dry=Count("id", filter=Q(cargo_profile=VehicleCargoProfile.DRY_CARGO.value)),
        refrigerated=Count(
            "id", filter=Q(cargo_profile=VehicleCargoProfile.REFRIGERATED_CARGO.value)
        ),
        both=Count("id", filter=Q(cargo_profile=VehicleCargoProfile.BOTH.value)),
    )

    driver_documents_qs = scoped_driver_document_queryset(user, PermissionCode.DOCUMENTS_VIEW)
    vehicle_documents_qs = scoped_vehicle_document_queryset(user, PermissionCode.DOCUMENTS_VIEW)
    carrier_documents_qs = scoped_carrier_document_queryset(user, PermissionCode.DOCUMENTS_VIEW)
    document_kpi = document_kpis(
        driver_documents_qs=driver_documents_qs,
        vehicle_documents_qs=vehicle_documents_qs,
        carrier_documents_qs=carrier_documents_qs,
    )
    driver_compliant = 0
    for driver in drivers_qs.prefetch_related("documents"):
        if (
            evaluate_entity_compliance(
                entity_type=EntityType.DRIVER, documents=driver.documents.all()
            ).status
            == ComplianceStatus.COMPLIANT
        ):
            driver_compliant += 1
    vehicle_compliant = 0
    for vehicle in vehicles_qs.prefetch_related("documents"):
        if (
            evaluate_entity_compliance(
                entity_type=EntityType.VEHICLE, documents=vehicle.documents.all()
            ).status
            == ComplianceStatus.COMPLIANT
        ):
            vehicle_compliant += 1
    carrier_compliant = 0
    for carrier in carriers_qs.prefetch_related("documents"):
        if (
            evaluate_entity_compliance(
                entity_type=EntityType.CARRIER, documents=carrier.documents.all()
            ).status
            == ComplianceStatus.COMPLIANT
        ):
            carrier_compliant += 1

    freight_qs = (
        scoped_freight_request_queryset(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
        if _has_permission(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
        else FreightRequest.objects.none()
    )
    today = timezone.now().date()
    freight_stats = freight_qs.aggregate(
        total=Count("id"),
        open=Count(
            "id",
            filter=Q(
                status__in=[
                    FreightRequestStatus.DRAFT.value,
                    FreightRequestStatus.SUBMITTED.value,
                    FreightRequestStatus.UNDER_REVIEW.value,
                ]
            ),
        ),
        drafts=Count("id", filter=Q(status=FreightRequestStatus.DRAFT.value)),
        submitted=Count("id", filter=Q(status=FreightRequestStatus.SUBMITTED.value)),
        under_review=Count("id", filter=Q(status=FreightRequestStatus.UNDER_REVIEW.value)),
        cancelled=Count("id", filter=Q(status=FreightRequestStatus.CANCELLED.value)),
        refrigerated=Count(
            "id", filter=Q(cargo__cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value)
        ),
        ready_to_publish=Count("id", filter=Q(status=FreightRequestStatus.READY_TO_PUBLISH.value)),
        created_today=Count("id", filter=Q(created_at__date=today)),
    )

    quote_qs = (
        scoped_freight_quote_queryset(user, PermissionCode.FREIGHT_QUOTES_VIEW)
        if _has_permission(user, PermissionCode.FREIGHT_QUOTES_VIEW)
        else FreightQuote.objects.none()
    )
    quote_stats = quote_qs.aggregate(
        total=Count("id"),
        drafts=Count("id", filter=Q(status=FreightQuoteStatus.DRAFT.value)),
        under_review=Count("id", filter=Q(status=FreightQuoteStatus.UNDER_REVIEW.value)),
        approved=Count("id", filter=Q(status=FreightQuoteStatus.APPROVED.value)),
        sent=Count("id", filter=Q(status=FreightQuoteStatus.SENT.value)),
        expired=Count("id", filter=Q(status=FreightQuoteStatus.EXPIRED.value)),
        open=Count(
            "id",
            filter=Q(
                status__in=[
                    FreightQuoteStatus.DRAFT.value,
                    FreightQuoteStatus.UNDER_REVIEW.value,
                    FreightQuoteStatus.APPROVED.value,
                ]
            ),
        ),
    )
    quote_value_total = 0
    quote_margin_total = 0
    if _has_permission(user, PermissionCode.FREIGHT_QUOTES_VIEW_MARGIN):
        quote_value_total = quote_qs.aggregate(total=Sum("total_amount"))["total"] or 0
        for quote in quote_qs.filter(estimated_cost__isnull=False).only(
            "customer_price", "estimated_cost"
        ):
            quote_margin_total += quote.gross_margin_amount or 0

    offer_qs = (
        scoped_freight_offer_queryset(user, PermissionCode.FREIGHT_OFFERS_VIEW)
        if _has_permission(user, PermissionCode.FREIGHT_OFFERS_VIEW)
        else FreightOffer.objects.none()
    )
    expiring_soon = timezone.now() + timezone.timedelta(days=2)
    offer_stats = offer_qs.aggregate(
        total=Count("id"),
        drafts=Count("id", filter=Q(status=FreightOfferStatus.DRAFT.value)),
        ready=Count("id", filter=Q(status=FreightOfferStatus.READY.value)),
        published=Count("id", filter=Q(status=FreightOfferStatus.PUBLISHED.value)),
        paused=Count("id", filter=Q(status=FreightOfferStatus.PAUSED.value)),
        expired=Count("id", filter=Q(status=FreightOfferStatus.EXPIRED.value)),
        cancelled=Count("id", filter=Q(status=FreightOfferStatus.CANCELLED.value)),
        refrigerated=Count(
            "id",
            filter=Q(premises_snapshot__cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value),
        ),
        expiring_soon=Count(
            "id",
            filter=Q(
                status__in=[
                    FreightOfferStatus.PUBLISHED.value,
                    FreightOfferStatus.PAUSED.value,
                ],
                expires_at__lte=expiring_soon,
                expires_at__gt=timezone.now(),
            ),
        ),
    )
    offer_value_total = 0
    offer_spread_total = 0
    if _has_permission(user, PermissionCode.FREIGHT_OFFERS_VIEW_MARGIN):
        offer_value_total = offer_qs.aggregate(total=Sum("offer_amount"))["total"] or 0
        quoted_for_spread = offer_qs.select_related("freight_quote").filter(
            freight_quote__isnull=False
        )
        for offer in quoted_for_spread:
            spread = offer.spread_amount
            if spread is not None:
                offer_spread_total += spread
    elif _has_permission(user, PermissionCode.FREIGHT_OFFERS_VIEW):
        offer_value_total = (
            offer_qs.filter(status=FreightOfferStatus.PUBLISHED.value).aggregate(
                total=Sum("offer_amount")
            )["total"]
            or 0
        )

    return {
        "users_total": users_qs.count() if users_qs is not None else 0,
        "customers_total": customer_stats["total"],
        "customers_active": customer_stats["active"],
        "customers_prospects": customer_stats["prospects"],
        "carriers_total": carrier_stats["total"],
        "carriers_active": carrier_stats["active"],
        "carriers_pending": carrier_stats["pending"],
        "drivers_total": driver_stats["total"],
        "drivers_active": driver_stats["active"],
        "drivers_pending": driver_stats["pending"],
        "drivers_blocked": driver_stats["blocked"],
        "drivers_available": driver_stats["available"],
        "vehicles_total": vehicle_stats["total"],
        "vehicles_active": vehicle_stats["active"],
        "vehicles_blocked": vehicle_stats["blocked"],
        "vehicles_maintenance": vehicle_stats["maintenance"],
        "vehicles_available": vehicle_stats["available"],
        "vehicles_dry": vehicle_stats["dry"],
        "vehicles_refrigerated": vehicle_stats["refrigerated"],
        "vehicles_both": vehicle_stats["both"],
        "documents_total": document_kpi["total"],
        "documents_pending": document_kpi["pending"],
        "documents_pending_review": document_kpi["pending_review"],
        "documents_approved": document_kpi["approved"],
        "documents_rejected": document_kpi["rejected"],
        "documents_expired": document_kpi["expired"],
        "documents_expiring_30": document_kpi["expiring_30"],
        "documents_expiring_15": document_kpi["expiring_15"],
        "documents_expiring_7": document_kpi["expiring_7"],
        "documents_driver_pending": driver_documents_qs.filter(
            status=DocumentStatus.PENDING.value
        ).count(),
        "documents_driver_under_review": driver_documents_qs.filter(
            status=DocumentStatus.UNDER_REVIEW.value
        ).count(),
        "documents_driver_approved": driver_documents_qs.filter(
            status=DocumentStatus.APPROVED.value
        ).count(),
        "documents_driver_rejected": driver_documents_qs.filter(
            status=DocumentStatus.REJECTED.value
        ).count(),
        "documents_driver_expired": driver_documents_qs.filter(expired_filter())
        .exclude(status=DocumentStatus.REPLACED.value)
        .count(),
        "documents_vehicle_pending": vehicle_documents_qs.filter(
            status=DocumentStatus.PENDING.value
        ).count(),
        "documents_vehicle_under_review": vehicle_documents_qs.filter(
            status=DocumentStatus.UNDER_REVIEW.value
        ).count(),
        "documents_vehicle_approved": vehicle_documents_qs.filter(
            status=DocumentStatus.APPROVED.value
        ).count(),
        "documents_vehicle_rejected": vehicle_documents_qs.filter(
            status=DocumentStatus.REJECTED.value
        ).count(),
        "documents_vehicle_expired": vehicle_documents_qs.filter(expired_filter())
        .exclude(status=DocumentStatus.REPLACED.value)
        .count(),
        "documents_carrier_pending": carrier_documents_qs.filter(
            status=DocumentStatus.PENDING.value
        ).count(),
        "documents_carrier_under_review": carrier_documents_qs.filter(
            status=DocumentStatus.UNDER_REVIEW.value
        ).count(),
        "documents_carrier_approved": carrier_documents_qs.filter(
            status=DocumentStatus.APPROVED.value
        ).count(),
        "documents_carrier_rejected": carrier_documents_qs.filter(
            status=DocumentStatus.REJECTED.value
        ).count(),
        "documents_carrier_expired": carrier_documents_qs.filter(expired_filter())
        .exclude(status=DocumentStatus.REPLACED.value)
        .count(),
        "documents_vehicle_crlv_expiring": vehicle_documents_qs.filter(
            document_type=VehicleDocumentType.CRLV.value
        )
        .filter(expiration_window_filter(days=30))
        .exclude(status__in=[DocumentStatus.EXPIRED.value, DocumentStatus.REPLACED.value])
        .count(),
        "documents_vehicle_crlv_expired": vehicle_documents_qs.filter(
            document_type=VehicleDocumentType.CRLV.value
        )
        .filter(expired_filter())
        .exclude(status=DocumentStatus.REPLACED.value)
        .count(),
        "entities_driver_compliant": driver_compliant,
        "entities_vehicle_compliant": vehicle_compliant,
        "entities_carrier_compliant": carrier_compliant,
        "freight_requests_total": freight_stats["total"],
        "freight_requests_open": freight_stats["open"],
        "freight_requests_drafts": freight_stats["drafts"],
        "freight_requests_submitted": freight_stats["submitted"],
        "freight_requests_under_review": freight_stats["under_review"],
        "freight_requests_cancelled": freight_stats["cancelled"],
        "freight_requests_refrigerated": freight_stats["refrigerated"],
        "freight_requests_ready_to_publish": freight_stats["ready_to_publish"],
        "freight_requests_today": freight_stats["created_today"],
        "freight_quotes_total": quote_stats["total"],
        "freight_quotes_open": quote_stats["open"],
        "freight_quotes_drafts": quote_stats["drafts"],
        "freight_quotes_under_review": quote_stats["under_review"],
        "freight_quotes_approved": quote_stats["approved"],
        "freight_quotes_sent": quote_stats["sent"],
        "freight_quotes_expired": quote_stats["expired"],
        "freight_quotes_value_total": quote_value_total,
        "freight_quotes_margin_total": quote_margin_total,
        "freight_offers_total": offer_stats["total"],
        "freight_offers_drafts": offer_stats["drafts"],
        "freight_offers_ready": offer_stats["ready"],
        "freight_offers_published": offer_stats["published"],
        "freight_offers_paused": offer_stats["paused"],
        "freight_offers_expired": offer_stats["expired"],
        "freight_offers_cancelled": offer_stats["cancelled"],
        "freight_offers_refrigerated": offer_stats["refrigerated"],
        "freight_offers_expiring_soon": offer_stats["expiring_soon"],
        "freight_offers_value_total": offer_value_total,
        "freight_offers_spread_total": offer_spread_total,
    }


class DashboardBaseView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    active_menu = "dashboard"
    chart_key = "overview"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            (self.page_title, None),
        )

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {"charts": []}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        snapshot = _dashboard_snapshot(self.request.user)
        context["snapshot"] = snapshot
        context["chart_payload"] = self.get_chart_payload(snapshot)
        context["chart_key"] = self.chart_key
        return context


class DashboardOperationsView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/operations.html"
    permission_code = PermissionCode.DRIVERS_VIEW
    page_title = "Operação"
    chart_key = "operations"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "activity",
                    "library": "chartjs",
                    "type": "line",
                    "labels": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"],
                    "datasets": [
                        {"label": "Motoristas ativos", "data": [snapshot["drivers_active"]] * 7},
                        {
                            "label": "Veículos disponíveis",
                            "data": [snapshot["vehicles_available"]] * 7,
                        },
                    ],
                },
                {
                    "id": "operations_mix",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Motoristas disponíveis", "data": [snapshot["drivers_available"]]},
                        {"name": "Veículos disponíveis", "data": [snapshot["vehicles_available"]]},
                        {
                            "name": "Solicitações abertas",
                            "data": [snapshot["freight_requests_open"]],
                        },
                    ],
                    "categories": ["Atual"],
                },
            ]
        }


class DashboardRelationshipView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/relationship.html"
    permission_code = PermissionCode.CUSTOMERS_VIEW
    page_title = "Relacionamento"
    chart_key = "relationship"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "overview-chart",
                    "library": "apex",
                    "type": "donut",
                    "series": [
                        snapshot["customers_active"],
                        snapshot["customers_prospects"],
                        snapshot["carriers_total"],
                        snapshot["users_total"],
                    ],
                    "labels": [
                        "Clientes ativos",
                        "Prospects",
                        "Transportadoras",
                        "Responsáveis",
                    ],
                },
                {
                    "id": "visitors-chart",
                    "library": "apex",
                    "type": "line",
                    "series": [
                        {
                            "name": "Base de relacionamento",
                            "data": [
                                snapshot["customers_total"],
                                snapshot["carriers_total"],
                                snapshot["users_total"],
                            ],
                        }
                    ],
                    "categories": ["Clientes", "Transportadoras", "Responsáveis"],
                },
            ]
        }


class DashboardFinanceView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/finance.html"
    permission_code = PermissionCode.AUDIT_VIEW
    page_title = "Financeiro"
    chart_key = "finance"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "chartBar",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Receita", "data": [0, 0, 0, 0]},
                        {"name": "Despesa", "data": [0, 0, 0, 0]},
                    ],
                    "categories": ["Q1", "Q2", "Q3", "Q4"],
                },
                {
                    "id": "expensesChart",
                    "library": "apex",
                    "type": "area",
                    "series": [{"name": "Fluxo", "data": [0, 0, 0, 0, 0, 0]}],
                    "categories": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"],
                },
                {
                    "id": "redial",
                    "library": "apex",
                    "type": "radialBar",
                    "series": [0],
                    "labels": ["Integração domínio financeiro"],
                },
            ]
        }


class DashboardAnalyticsView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/analytics.html"
    permission_code = PermissionCode.USERS_VIEW
    page_title = "Analytics"
    chart_key = "analytics"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "overview-chart",
                    "library": "apex",
                    "type": "donut",
                    "series": [0, 0, 0],
                    "labels": ["GA4", "Google Ads", "Search Console"],
                },
                {
                    "id": "updates-chart",
                    "library": "apex",
                    "type": "line",
                    "series": [{"name": "Sessões", "data": [0, 0, 0, 0, 0, 0]}],
                    "categories": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"],
                },
                {
                    "id": "visitors-chart",
                    "library": "apex",
                    "type": "bar",
                    "series": [{"name": "Conversões", "data": [0, 0, 0]}],
                    "categories": ["Orgânico", "Pago", "Direto"],
                },
            ]
        }


class DashboardCommercialView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/commercial.html"
    permission_code = PermissionCode.CUSTOMERS_VIEW
    page_title = "Comercial"
    chart_key = "commercial"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "NewCustomers",
                    "library": "apex",
                    "type": "area",
                    "series": [
                        {"name": "Clientes", "data": [snapshot["customers_total"]] * 6},
                        {
                            "name": "Solicitações",
                            "data": [snapshot["freight_requests_total"]] * 6,
                        },
                    ],
                    "categories": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"],
                },
                {
                    "id": "NewExperience",
                    "library": "apex",
                    "type": "line",
                    "series": [
                        {"name": "Ativos", "data": [snapshot["customers_active"]] * 6},
                        {
                            "name": "Submetidas",
                            "data": [snapshot["freight_requests_submitted"]] * 6,
                        },
                    ],
                    "categories": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"],
                },
                {
                    "id": "projectChart",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Clientes", "data": [snapshot["customers_total"]]},
                        {"name": "Responsáveis", "data": [snapshot["users_total"]]},
                    ],
                    "categories": ["Atual"],
                },
            ]
        }


class DashboardMarketplaceView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/marketplace.html"
    permission_code = PermissionCode.CARRIERS_VIEW
    page_title = "Marketplace"
    chart_key = "marketplace"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "handleWeeklySales",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Transportadoras", "data": [snapshot["carriers_total"]] * 6},
                        {
                            "name": "Solicitações prontas",
                            "data": [snapshot["freight_requests_ready_to_publish"]] * 6,
                        },
                    ],
                    "categories": ["S1", "S2", "S3", "S4", "S5", "S6"],
                },
                {
                    "id": "handleOrderChart",
                    "library": "apex",
                    "type": "line",
                    "series": [{"name": "Motoristas", "data": [snapshot["drivers_total"]] * 6}],
                    "categories": ["S1", "S2", "S3", "S4", "S5", "S6"],
                },
                {
                    "id": "handleMarketShare",
                    "library": "apex",
                    "type": "donut",
                    "series": [
                        snapshot["customers_total"],
                        snapshot["carriers_total"],
                        snapshot["drivers_total"],
                        snapshot["vehicles_total"],
                    ],
                    "labels": ["Clientes", "Transportadoras", "Motoristas", "Veículos"],
                },
            ]
        }


class DashboardComplianceView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/compliance.html"
    permission_code = PermissionCode.COMPLIANCE_VIEW
    page_title = "Compliance"
    chart_key = "compliance"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "chartBar",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Pendentes", "data": [snapshot["documents_driver_pending"]]},
                        {
                            "name": "Em análise",
                            "data": [snapshot["documents_driver_under_review"]],
                        },
                        {"name": "Aprovados", "data": [snapshot["documents_driver_approved"]]},
                        {"name": "Rejeitados", "data": [snapshot["documents_driver_rejected"]]},
                        {"name": "Vencidos", "data": [snapshot["documents_driver_expired"]]},
                    ],
                    "categories": ["Motoristas"],
                },
                {
                    "id": "projectChart",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Pendentes", "data": [snapshot["documents_vehicle_pending"]]},
                        {
                            "name": "Em análise",
                            "data": [snapshot["documents_vehicle_under_review"]],
                        },
                        {"name": "Aprovados", "data": [snapshot["documents_vehicle_approved"]]},
                        {"name": "Rejeitados", "data": [snapshot["documents_vehicle_rejected"]]},
                        {"name": "Vencidos", "data": [snapshot["documents_vehicle_expired"]]},
                    ],
                    "categories": ["Veículos"],
                },
                {
                    "id": "activity",
                    "library": "apex",
                    "type": "area",
                    "series": [
                        {
                            "name": "Backlog compliance",
                            "data": [
                                snapshot["documents_pending"] + snapshot["documents_pending_review"]
                            ],
                        }
                    ],
                    "categories": ["Atual"],
                },
            ]
        }


class DashboardFleetHealthView(DashboardBaseView):
    template_name = "backoffice/pages/dashboards/fleet_health.html"
    permission_code = PermissionCode.VEHICLES_VIEW
    page_title = "Saúde da Frota"
    chart_key = "fleet-health"

    def get_chart_payload(self, snapshot: dict[str, int]) -> dict:
        return {
            "charts": [
                {
                    "id": "overiewChart",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {"name": "Ativos", "data": [snapshot["vehicles_active"]]},
                        {"name": "Disponíveis", "data": [snapshot["vehicles_available"]]},
                        {"name": "Manutenção", "data": [snapshot["vehicles_maintenance"]]},
                        {"name": "Bloqueados", "data": [snapshot["vehicles_blocked"]]},
                    ],
                    "categories": ["Frota"],
                },
                {
                    "id": "redial",
                    "library": "apex",
                    "type": "radialBar",
                    "series": [
                        round(
                            (snapshot["vehicles_available"] / snapshot["vehicles_total"]) * 100, 2
                        )
                        if snapshot["vehicles_total"]
                        else 0
                    ],
                    "labels": ["Disponibilidade"],
                },
                {
                    "id": "overview-chart",
                    "library": "apex",
                    "type": "donut",
                    "series": [
                        snapshot["vehicles_dry"],
                        snapshot["vehicles_refrigerated"],
                        snapshot["vehicles_both"],
                    ],
                    "labels": ["Carga seca", "Refrigerado", "Ambas"],
                },
                {
                    "id": "documentsChart",
                    "library": "apex",
                    "type": "bar",
                    "series": [
                        {
                            "name": "CRLV vencendo",
                            "data": [snapshot["documents_vehicle_crlv_expiring"]],
                        },
                        {
                            "name": "CRLV vencido",
                            "data": [snapshot["documents_vehicle_crlv_expired"]],
                        },
                        {
                            "name": "Docs pendentes",
                            "data": [snapshot["documents_vehicle_pending"]],
                        },
                    ],
                    "categories": ["Documentação"],
                },
            ]
        }


class OrganizationListView(FilteredListView):
    template_name = "backoffice/pages/organizations/list.html"
    context_object_name = "organizations"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Organizations"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Organizations", None))

    def get_queryset(self):
        queryset = scoped_organization_queryset(
            self.request.user, self.permission_code
        ).prefetch_related("business_units", "branches", "departments", "teams")
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if query:
            queryset = queryset.filter(name__icontains=query)
        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)
        return queryset


class OrganizationDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/organizations/detail.html"
    context_object_name = "organization"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Organization"

    def get_queryset(self):
        queryset = scoped_organization_queryset(self.request.user, self.permission_code)
        return queryset.prefetch_related(
            "business_units",
            "branches__business_unit",
            "departments__branch",
            "teams__department",
            "memberships__user",
            "memberships__membership_roles__role",
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            (self.object.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_view_memberships"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.MEMBERSHIPS_VIEW
        )
        return context


class UserCreateForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome de usuário"}),
        label="Username",
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "E-mail"}),
        label="E-mail",
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome"}),
        label="Nome",
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Sobrenome"}),
        label="Sobrenome",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Senha"}),
        label="Senha",
    )
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Organização",
    )
    role = forms.ModelChoiceField(
        queryset=Role.objects.all(),
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Função (Role)",
    )
    scope = forms.ChoiceField(
        choices=[(scope.value, scope.value) for scope in AccessScope],
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Escopo de Acesso",
        initial=AccessScope.COMPANY.value,
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.ORGANIZATIONS_VIEW
            )

    def clean_username(self):
        from django.contrib.auth import get_user_model

        username = self.cleaned_data["username"]
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise ValidationError("Este nome de usuário já está em uso.")
        return username


class UserUpdateForm(forms.ModelForm):
    class Meta:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        model = User
        fields = ["email", "first_name", "last_name", "is_active"]
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "legal_name", "document", "type", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "legal_name": forms.TextInput(attrs={"class": "form-control"}),
            "document": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BusinessUnitForm(forms.ModelForm):
    class Meta:
        model = BusinessUnit
        fields = ["organization", "name", "is_active"]
        widgets = {
            "organization": forms.Select(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["organization", "business_unit", "name", "code", "is_active"]
        widgets = {
            "organization": forms.Select(attrs={"class": "form-control"}),
            "business_unit": forms.Select(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )
            self.fields["business_unit"].queryset = scoped_business_unit_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )

    def clean(self):
        cleaned_data = super().clean()
        bu = cleaned_data.get("business_unit")
        org = cleaned_data.get("organization")
        if bu and org and bu.organization != org:
            self.add_error(
                "business_unit", "A Unidade de Negócio deve pertencer à mesma Organização."
            )
        return cleaned_data


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["organization", "branch", "name", "is_active"]
        widgets = {
            "organization": forms.Select(attrs={"class": "form-control"}),
            "branch": forms.Select(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )
            self.fields["branch"].queryset = scoped_branch_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )

    def clean(self):
        cleaned_data = super().clean()
        branch = cleaned_data.get("branch")
        org = cleaned_data.get("organization")
        if branch and org and branch.organization != org:
            self.add_error("branch", "A Filial deve pertencer à mesma Organização.")
        return cleaned_data


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["organization", "department", "name", "is_active"]
        widgets = {
            "organization": forms.Select(attrs={"class": "form-control"}),
            "department": forms.Select(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )
            self.fields["department"].queryset = scoped_department_queryset(
                user, PermissionCode.ORGANIZATIONS_MANAGE
            )

    def clean(self):
        cleaned_data = super().clean()
        dept = cleaned_data.get("department")
        org = cleaned_data.get("organization")
        if dept and org and dept.organization != org:
            self.add_error("department", "O Departamento deve pertencer à mesma Organização.")
        return cleaned_data


class MembershipForm(forms.ModelForm):
    role = forms.ModelChoiceField(
        queryset=Role.objects.all(),
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Função (Role)",
    )
    scope = forms.ChoiceField(
        choices=[(scope.value, scope.value) for scope in AccessScope],
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Escopo de Acesso",
        initial=AccessScope.COMPANY.value,
    )

    class Meta:
        model = Membership
        fields = [
            "user",
            "organization",
            "business_unit",
            "branch",
            "department",
            "team",
            "status",
        ]
        widgets = {
            "user": forms.Select(attrs={"class": "form-control"}),
            "organization": forms.Select(attrs={"class": "form-control"}),
            "business_unit": forms.Select(attrs={"class": "form-control"}),
            "branch": forms.Select(attrs={"class": "form-control"}),
            "department": forms.Select(attrs={"class": "form-control"}),
            "team": forms.Select(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["user"].queryset = scoped_user_queryset(user, PermissionCode.USERS_VIEW)
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.ORGANIZATIONS_VIEW
            )
            self.fields["business_unit"].queryset = scoped_business_unit_queryset(
                user, PermissionCode.ORGANIZATIONS_VIEW
            )
            self.fields["branch"].queryset = scoped_branch_queryset(
                user, PermissionCode.ORGANIZATIONS_VIEW
            )
            self.fields["department"].queryset = scoped_department_queryset(
                user, PermissionCode.ORGANIZATIONS_VIEW
            )
            self.fields["team"].queryset = scoped_team_queryset(
                user, PermissionCode.ORGANIZATIONS_VIEW
            )

        if self.instance and self.instance.pk:
            binding = MembershipRole.objects.filter(membership=self.instance).first()
            if binding:
                self.fields["role"].initial = binding.role
                self.fields["scope"].initial = binding.scope

    def clean(self):
        cleaned_data = super().clean()
        org = cleaned_data.get("organization")
        bu = cleaned_data.get("business_unit")
        branch = cleaned_data.get("branch")
        dept = cleaned_data.get("department")
        team = cleaned_data.get("team")

        if bu and org and bu.organization != org:
            self.add_error(
                "business_unit", "A Unidade de Negócio deve pertencer à mesma Organização."
            )
        if branch and org and branch.organization != org:
            self.add_error("branch", "A Filial deve pertencer à mesma Organização.")
        if dept and org and dept.organization != org:
            self.add_error("department", "O Departamento deve pertencer à mesma Organização.")
        if team and org and team.organization != org:
            self.add_error("team", "A Equipe deve pertencer à mesma Organização.")
        return cleaned_data


class UserListView(FilteredListView):
    template_name = "backoffice/pages/users/list.html"
    context_object_name = "users"
    permission_code = PermissionCode.USERS_VIEW
    active_menu = "users"
    page_title = "Users"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Users", None))

    def get_queryset(self):
        queryset = scoped_user_queryset(self.request.user, self.permission_code).prefetch_related(
            "memberships__organization",
            "memberships__membership_roles__role",
            "memberships__team",
        )
        q = self.request.GET.get("q", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        role = self.request.GET.get("role", "").strip()
        team = self.request.GET.get("team", "").strip()
        active = self.request.GET.get("active", "").strip()

        if q:
            queryset = queryset.filter(
                django_models.Q(username__icontains=q)
                | django_models.Q(email__icontains=q)
                | django_models.Q(first_name__icontains=q)
                | django_models.Q(last_name__icontains=q)
            )
        if organization:
            queryset = queryset.filter(memberships__organization_id=organization)
        if role:
            queryset = queryset.filter(memberships__membership_roles__role_id=role)
        if team:
            queryset = queryset.filter(memberships__team_id=team)
        if active == "yes":
            queryset = queryset.filter(is_active=True)
        elif active == "no":
            queryset = queryset.filter(is_active=False)

        return queryset.order_by("username").distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organizations"] = scoped_organization_queryset(
            self.request.user, PermissionCode.ORGANIZATIONS_VIEW
        )
        context["roles"] = Role.objects.all()
        context["teams"] = scoped_team_queryset(
            self.request.user, PermissionCode.ORGANIZATIONS_VIEW
        )
        context["can_create_user"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.USERS_CREATE
        )
        return context


class UserDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/users/detail.html"
    context_object_name = "account"
    permission_code = PermissionCode.USERS_VIEW
    active_menu = "users"
    page_title = "User"

    def get_queryset(self):
        return scoped_user_queryset(self.request.user, self.permission_code).prefetch_related(
            "memberships__organization", "memberships__membership_roles__role"
        )

    def get_breadcrumbs(self):
        label = self.object.email or self.object.username
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Users", reverse_lazy("backoffice:users")),
            (label, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_edit_user"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.USERS_UPDATE
        )
        context["can_manage_memberships"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.MEMBERSHIPS_MANAGE
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:8]
        return context


class UserCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/users/form.html"
    permission_code = PermissionCode.USERS_CREATE
    active_menu = "users"
    page_title = "Novo Usuário"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Users", reverse_lazy("backoffice:users")),
        ("Novo Usuário", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = UserCreateForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = UserCreateForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                user = create_user_with_membership(
                    username=form.cleaned_data["username"],
                    email=form.cleaned_data["email"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    password=form.cleaned_data["password"],
                    organization=form.cleaned_data["organization"],
                    role=form.cleaned_data["role"],
                    scope=form.cleaned_data["scope"],
                    actor=request.user,
                )
                return redirect("backoffice:user_detail", pk=user.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class UserUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/users/form.html"
    permission_code = PermissionCode.USERS_UPDATE
    active_menu = "users"
    page_title = "Editar Usuário"

    def get_object(self):
        from django.contrib.auth import get_user_model

        get_user_model()
        queryset = scoped_user_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        label = obj.email or obj.username
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Users", reverse_lazy("backoffice:users")),
            (label, reverse_lazy("backoffice:user_detail", args=[obj.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = UserUpdateForm(instance=obj)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        user = self.get_object()
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            try:
                update_user_details(
                    user,
                    email=form.cleaned_data["email"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:user_detail", pk=user.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class UserStatusChangeView(BackofficePermissionMixin, TemplateView):
    permission_code = PermissionCode.USERS_UPDATE

    def post(self, request, *args, **kwargs):
        from django.contrib.auth import get_user_model

        get_user_model()
        queryset = scoped_user_queryset(request.user, self.permission_code)
        user = get_object_or_404(queryset, pk=kwargs["pk"])
        action = request.POST.get("action")
        if action == "activate":
            update_user_details(
                user,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                is_active=True,
                actor=request.user,
            )
        elif action == "deactivate":
            update_user_details(
                user,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                is_active=False,
                actor=request.user,
            )
        return redirect("backoffice:user_detail", pk=user.pk)


class OrganizationCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/organizations/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Nova Organização"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Nova Organização", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = OrganizationForm()
        return context

    def post(self, request, *args, **kwargs):
        form = OrganizationForm(request.POST)
        if form.is_valid():
            try:
                org = create_organization(
                    name=form.cleaned_data["name"],
                    legal_name=form.cleaned_data["legal_name"],
                    document=form.cleaned_data["document"],
                    type=form.cleaned_data["type"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:organization_detail", pk=org.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class OrganizationUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/organizations/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Editar Organização"

    def get_object(self):
        queryset = scoped_organization_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            (obj.name, reverse_lazy("backoffice:organization_detail", args=[obj.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = OrganizationForm(instance=obj)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        org = self.get_object()
        form = OrganizationForm(request.POST, instance=org)
        if form.is_valid():
            try:
                update_organization(
                    org,
                    name=form.cleaned_data["name"],
                    legal_name=form.cleaned_data["legal_name"],
                    document=form.cleaned_data["document"],
                    type=form.cleaned_data["type"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:organization_detail", pk=org.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class BusinessUnitListView(FilteredListView):
    template_name = "backoffice/pages/business_units/list.html"
    context_object_name = "business_units"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Unidades de Negócio"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Unidades de Negócio", None),
    )

    def get_queryset(self):
        queryset = scoped_business_unit_queryset(
            self.request.user, self.permission_code
        ).select_related("organization")
        q = self.request.GET.get("q", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        if q:
            queryset = queryset.filter(name__icontains=q)
        if organization:
            queryset = queryset.filter(organization_id=organization)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organizations"] = scoped_organization_queryset(
            self.request.user, self.permission_code
        )
        context["can_manage_organizations"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.ORGANIZATIONS_MANAGE
        )
        return context


class BusinessUnitCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/business_units/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Nova Unidade de Negócio"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Unidades de Negócio", reverse_lazy("backoffice:business_units")),
        ("Nova", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = BusinessUnitForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = BusinessUnitForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                create_business_unit(
                    organization=form.cleaned_data["organization"],
                    name=form.cleaned_data["name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:business_units")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class BusinessUnitUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/business_units/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Editar Unidade de Negócio"

    def get_object(self):
        queryset = scoped_business_unit_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            ("Unidades de Negócio", reverse_lazy("backoffice:business_units")),
            (obj.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = BusinessUnitForm(instance=obj, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        bu = self.get_object()
        form = BusinessUnitForm(request.POST, instance=bu, user=request.user)
        if form.is_valid():
            try:
                update_business_unit(
                    bu,
                    name=form.cleaned_data["name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:business_units")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class BranchListView(FilteredListView):
    template_name = "backoffice/pages/branches/list.html"
    context_object_name = "branches"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Filiais"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Filiais", None),
    )

    def get_queryset(self):
        queryset = scoped_branch_queryset(self.request.user, self.permission_code).select_related(
            "organization", "business_unit"
        )
        q = self.request.GET.get("q", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        if q:
            queryset = queryset.filter(name__icontains=q)
        if organization:
            queryset = queryset.filter(organization_id=organization)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organizations"] = scoped_organization_queryset(
            self.request.user, self.permission_code
        )
        context["can_manage_organizations"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.ORGANIZATIONS_MANAGE
        )
        return context


class BranchCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/branches/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Nova Filial"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Filiais", reverse_lazy("backoffice:branches")),
        ("Nova", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = BranchForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = BranchForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                create_branch(
                    organization=form.cleaned_data["organization"],
                    business_unit=form.cleaned_data["business_unit"],
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:branches")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class BranchUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/branches/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Editar Filial"

    def get_object(self):
        queryset = scoped_branch_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            ("Filiais", reverse_lazy("backoffice:branches")),
            (obj.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = BranchForm(instance=obj, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        branch = self.get_object()
        form = BranchForm(request.POST, instance=branch, user=request.user)
        if form.is_valid():
            try:
                update_branch(
                    branch,
                    business_unit=form.cleaned_data["business_unit"],
                    name=form.cleaned_data["name"],
                    code=form.cleaned_data["code"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:branches")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class DepartmentListView(FilteredListView):
    template_name = "backoffice/pages/departments/list.html"
    context_object_name = "departments"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Departamentos"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Departamentos", None),
    )

    def get_queryset(self):
        queryset = scoped_department_queryset(
            self.request.user, self.permission_code
        ).select_related("organization", "branch")
        q = self.request.GET.get("q", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        if q:
            queryset = queryset.filter(name__icontains=q)
        if organization:
            queryset = queryset.filter(organization_id=organization)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organizations"] = scoped_organization_queryset(
            self.request.user, self.permission_code
        )
        context["can_manage_organizations"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.ORGANIZATIONS_MANAGE
        )
        return context


class DepartmentCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/departments/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Novo Departamento"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Departamentos", reverse_lazy("backoffice:departments")),
        ("Novo", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = DepartmentForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = DepartmentForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                create_department(
                    organization=form.cleaned_data["organization"],
                    branch=form.cleaned_data["branch"],
                    name=form.cleaned_data["name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:departments")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class DepartmentUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/departments/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Editar Departamento"

    def get_object(self):
        queryset = scoped_department_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            ("Departamentos", reverse_lazy("backoffice:departments")),
            (obj.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = DepartmentForm(instance=obj, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        dept = self.get_object()
        form = DepartmentForm(request.POST, instance=dept, user=request.user)
        if form.is_valid():
            try:
                update_department(
                    dept,
                    branch=form.cleaned_data["branch"],
                    name=form.cleaned_data["name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:departments")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class TeamListView(FilteredListView):
    template_name = "backoffice/pages/teams/list.html"
    context_object_name = "teams"
    permission_code = PermissionCode.ORGANIZATIONS_VIEW
    active_menu = "organizations"
    page_title = "Equipes"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Equipes", None),
    )

    def get_queryset(self):
        queryset = scoped_team_queryset(self.request.user, self.permission_code).select_related(
            "organization", "department"
        )
        q = self.request.GET.get("q", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        if q:
            queryset = queryset.filter(name__icontains=q)
        if organization:
            queryset = queryset.filter(organization_id=organization)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organizations"] = scoped_organization_queryset(
            self.request.user, self.permission_code
        )
        context["can_manage_organizations"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.ORGANIZATIONS_MANAGE
        )
        return context


class TeamCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/teams/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Nova Equipe"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Organizations", reverse_lazy("backoffice:organizations")),
        ("Equipes", reverse_lazy("backoffice:teams")),
        ("Nova", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = TeamForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = TeamForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                create_team(
                    organization=form.cleaned_data["organization"],
                    department=form.cleaned_data["department"],
                    name=form.cleaned_data["name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:teams")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class TeamUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/teams/form.html"
    permission_code = PermissionCode.ORGANIZATIONS_MANAGE
    active_menu = "organizations"
    page_title = "Editar Equipe"

    def get_object(self):
        queryset = scoped_team_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Organizations", reverse_lazy("backoffice:organizations")),
            ("Equipes", reverse_lazy("backoffice:teams")),
            (obj.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = TeamForm(instance=obj, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        team = self.get_object()
        form = TeamForm(request.POST, instance=team, user=request.user)
        if form.is_valid():
            try:
                update_team(
                    team,
                    department=form.cleaned_data["department"],
                    name=form.cleaned_data["name"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                return redirect("backoffice:teams")
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class MembershipCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/memberships/form.html"
    permission_code = PermissionCode.MEMBERSHIPS_MANAGE
    active_menu = "memberships"
    page_title = "Novo Vínculo"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Memberships", reverse_lazy("backoffice:memberships")),
        ("Novo Vínculo", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = MembershipForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = MembershipForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                membership = form.save(commit=False)
                update_user_membership(
                    user=membership.user,
                    organization=membership.organization,
                    role=form.cleaned_data["role"],
                    scope=form.cleaned_data["scope"],
                    actor=request.user,
                )
                membership = Membership.objects.get(
                    user=membership.user, organization=membership.organization
                )
                membership.business_unit = form.cleaned_data["business_unit"]
                membership.branch = form.cleaned_data["branch"]
                membership.department = form.cleaned_data["department"]
                membership.team = form.cleaned_data["team"]
                membership.status = form.cleaned_data["status"]
                membership.save()

                return redirect("backoffice:membership_detail", pk=membership.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class MembershipUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/memberships/form.html"
    permission_code = PermissionCode.MEMBERSHIPS_MANAGE
    active_menu = "memberships"
    page_title = "Editar Vínculo"

    def get_object(self):
        queryset = scoped_membership_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Memberships", reverse_lazy("backoffice:memberships")),
            (str(obj), reverse_lazy("backoffice:membership_detail", args=[obj.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = MembershipForm(instance=obj, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        membership = self.get_object()
        form = MembershipForm(request.POST, instance=membership, user=request.user)
        if form.is_valid():
            try:
                m = form.save(commit=False)
                update_user_membership(
                    user=m.user,
                    organization=m.organization,
                    role=form.cleaned_data["role"],
                    scope=form.cleaned_data["scope"],
                    actor=request.user,
                )
                m.business_unit = form.cleaned_data["business_unit"]
                m.branch = form.cleaned_data["branch"]
                m.department = form.cleaned_data["department"]
                m.team = form.cleaned_data["team"]
                m.status = form.cleaned_data["status"]
                m.save()

                return redirect("backoffice:membership_detail", pk=m.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class MembershipListView(FilteredListView):
    template_name = "backoffice/pages/memberships/list.html"
    context_object_name = "memberships"
    permission_code = PermissionCode.MEMBERSHIPS_VIEW
    active_menu = "memberships"
    page_title = "Memberships"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Memberships", None))

    def get_queryset(self):
        queryset = scoped_membership_queryset(self.request.user, self.permission_code)
        queryset = queryset.select_related(
            "user", "organization", "business_unit", "branch", "department", "team"
        ).prefetch_related("membership_roles__role")
        organization = self.request.GET.get("organization", "").strip()
        user = self.request.GET.get("user", "").strip()
        role = self.request.GET.get("role", "").strip()
        if organization:
            queryset = queryset.filter(organization__name__icontains=organization)
        if user:
            queryset = queryset.filter(user__username__icontains=user)
        if role:
            queryset = queryset.filter(membership_roles__role__code__icontains=role)
        return queryset.distinct()


class MembershipDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/memberships/detail.html"
    context_object_name = "membership"
    permission_code = PermissionCode.MEMBERSHIPS_VIEW
    active_menu = "memberships"
    page_title = "Membership"

    def get_queryset(self):
        return (
            scoped_membership_queryset(self.request.user, self.permission_code)
            .select_related("user", "organization", "business_unit", "branch", "department", "team")
            .prefetch_related("membership_roles__role__permissions")
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Memberships", reverse_lazy("backoffice:memberships")),
            (str(self.object), None),
        )


class RoleListView(FilteredListView):
    model = Role
    template_name = "backoffice/pages/roles/list.html"
    context_object_name = "roles"
    permission_code = PermissionCode.ROLES_MANAGE
    active_menu = "roles"
    page_title = "Roles"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Roles", None))

    def get_queryset(self):
        return Role.objects.prefetch_related("permissions")


class RoleDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    model = Role
    template_name = "backoffice/pages/roles/detail.html"
    context_object_name = "role"
    permission_code = PermissionCode.ROLES_MANAGE
    active_menu = "roles"
    page_title = "Role"

    def get_queryset(self):
        return Role.objects.prefetch_related("role_permissions__permission")

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Roles", reverse_lazy("backoffice:roles")),
            (self.object.code, None),
        )


class PermissionListView(FilteredListView):
    model = Permission
    template_name = "backoffice/pages/permissions/list.html"
    context_object_name = "permissions"
    permission_code = PermissionCode.ROLES_MANAGE
    active_menu = "permissions"
    page_title = "Permissions"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Permissions", None))
    paginate_by = None

    def get_queryset(self):
        return Permission.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grouped = {}
        for permission in context["permissions"]:
            prefix = permission.code.split(".", 1)[0]
            grouped.setdefault(prefix, []).append(permission)
        context["grouped_permissions"] = grouped
        return context


class AuditLogListView(FilteredListView):
    template_name = "backoffice/pages/audit/list.html"
    context_object_name = "audit_logs"
    permission_code = PermissionCode.AUDIT_VIEW
    active_menu = "audit"
    page_title = "AuditLog"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Audit", None))

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor", "organization")
        grant = self.permission_grant()
        if not self.request.user.is_superuser and grant.scope.name != "ALL":
            organization_ids = [membership.organization_id for membership in grant.memberships]
            queryset = queryset.filter(organization_id__in=organization_ids)
        action = self.request.GET.get("action", "").strip()
        actor = self.request.GET.get("actor", "").strip()
        organization = self.request.GET.get("organization", "").strip()
        start = parse_date(self.request.GET.get("start", ""))
        end = parse_date(self.request.GET.get("end", ""))
        if action:
            queryset = queryset.filter(action__icontains=action)
        if actor:
            queryset = queryset.filter(actor__username__icontains=actor)
        if organization:
            queryset = queryset.filter(organization__name__icontains=organization)
        if start:
            queryset = queryset.filter(created_at__date__gte=start)
        if end:
            queryset = queryset.filter(created_at__date__lte=end)
        return queryset


class AuditLogDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/audit/detail.html"
    context_object_name = "audit_log"
    permission_code = PermissionCode.AUDIT_VIEW
    active_menu = "audit"
    page_title = "AuditLog"

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor", "organization")
        grant = self.permission_grant()
        if not self.request.user.is_superuser and grant.scope.name != "ALL":
            organization_ids = [membership.organization_id for membership in grant.memberships]
            queryset = queryset.filter(organization_id__in=organization_ids)
        return queryset

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Audit", reverse_lazy("backoffice:audit")),
            (self.object.action, None),
        )


class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = [
            "organization",
            "user",
            "full_name",
            "birth_date",
            "document",
            "engagement_type",
            "email",
            "phone",
            "mobile_phone",
            "postal_code",
            "street",
            "number",
            "complement",
            "district",
            "city",
            "state",
            "country",
            "driver_license_number",
            "driver_license_category",
            "driver_license_issue_state",
            "driver_license_expiration",
            "status",
            "availability_status",
        ]
        widgets = {
            "organization": forms.Select(attrs={"class": "form-control"}),
            "user": forms.Select(attrs={"class": "form-control"}),
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome"}),
            "birth_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "document": forms.TextInput(attrs={"class": "form-control", "placeholder": "CPF"}),
            "engagement_type": forms.Select(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "E-mail"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Telefone"}),
            "mobile_phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Celular"}
            ),
            "postal_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "CEP"}),
            "street": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rua"}),
            "number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número"}),
            "complement": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Complemento"}
            ),
            "district": forms.TextInput(attrs={"class": "form-control", "placeholder": "Bairro"}),
            "city": forms.TextInput(attrs={"class": "form-control", "placeholder": "Cidade"}),
            "state": forms.TextInput(attrs={"class": "form-control", "placeholder": "UF"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "driver_license_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Número CNH"}
            ),
            "driver_license_category": forms.Select(attrs={"class": "form-control"}),
            "driver_license_issue_state": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "UF emissão"}
            ),
            "driver_license_expiration": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "status": forms.Select(attrs={"class": "form-control"}),
            "availability_status": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["driver_license_category"].choices = [("", "Selecione")] + [
            (kind.value, kind.value) for kind in DriverLicenseCategory
        ]
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.DRIVERS_VIEW
            )
            self.fields["user"].queryset = scoped_user_queryset(user, PermissionCode.USERS_VIEW)


class DriverListView(FilteredListView):
    template_name = "backoffice/pages/drivers/list.html"
    context_object_name = "drivers"
    permission_code = PermissionCode.DRIVERS_VIEW
    active_menu = "drivers"
    page_title = "Motoristas"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Motoristas", None))

    def get_queryset(self):
        queryset = (
            scoped_driver_queryset(self.request.user, self.permission_code)
            .select_related("organization", "user")
            .prefetch_related("documents", "vehicle_assignments__vehicle", "carrier_links__carrier")
            .annotate(
                active_vehicle_count=Count(
                    "vehicle_assignments",
                    filter=django_models.Q(vehicle_assignments__active=True),
                    distinct=True,
                ),
                active_carrier_count=Count(
                    "carrier_links",
                    filter=django_models.Q(carrier_links__active=True),
                    distinct=True,
                ),
            )
        )
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        approval = self.request.GET.get("approval", "").strip()
        availability = self.request.GET.get("availability", "").strip()
        carrier = self.request.GET.get("carrier", "").strip()
        cnh_category = self.request.GET.get("cnh_category", "").strip()
        state = self.request.GET.get("state", "").strip().upper()
        engagement_type = self.request.GET.get("engagement_type", "").strip()
        if query:
            queryset = queryset.filter(
                django_models.Q(full_name__icontains=query)
                | django_models.Q(document__icontains=query)
                | django_models.Q(driver_license_number__icontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        if approval:
            queryset = queryset.filter(approval_status=approval)
        if availability:
            queryset = queryset.filter(availability_status=availability)
        if carrier:
            queryset = queryset.filter(
                carrier_links__active=True, carrier_links__carrier_id=carrier
            )
        if cnh_category:
            queryset = queryset.filter(driver_license_category=cnh_category)
        if state:
            queryset = queryset.filter(state=state)
        if engagement_type:
            queryset = queryset.filter(engagement_type=engagement_type)
        return queryset.order_by("full_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = scoped_driver_queryset(self.request.user, self.permission_code)
        context["driver_statuses"] = list(DriverStatus)
        context["approval_statuses"] = list(DriverApprovalStatus)
        context["availability_statuses"] = list(DriverAvailabilityStatus)
        context["driver_engagement_types"] = list(DriverEngagementType)
        context["driver_license_categories"] = list(DriverLicenseCategory)
        context["carriers"] = scoped_carrier_queryset(
            self.request.user, PermissionCode.CARRIERS_VIEW
        ).order_by("trade_name")
        context["can_create_driver"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVERS_CREATE
        )
        context["kpis"] = {
            "total": base_qs.count(),
            "active": base_qs.filter(status=DriverStatus.ACTIVE).count(),
            "pending": base_qs.filter(status=DriverStatus.PENDING).count(),
            "blocked": base_qs.filter(status=DriverStatus.BLOCKED).count(),
            "license_expiring": base_qs.filter(
                driver_license_expiration__lte=timezone.localdate() + timedelta(days=30),
                driver_license_expiration__gte=timezone.localdate(),
            ).count(),
        }
        return context


class DriverDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/drivers/detail.html"
    context_object_name = "driver"
    permission_code = PermissionCode.DRIVERS_VIEW
    active_menu = "drivers"
    page_title = "Motorista"

    def get_queryset(self):
        return (
            scoped_driver_queryset(self.request.user, self.permission_code)
            .select_related("organization", "user", "approved_by")
            .prefetch_related(
                "documents",
                "vehicle_assignments__vehicle",
                "carrier_links__carrier__organization",
                "carrier_links__carrier__tenant",
            )
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Motoristas", reverse_lazy("backoffice:drivers")),
            (self.object.full_name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_update_driver"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVERS_UPDATE
        )
        context["can_change_driver_status"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVERS_CHANGE_STATUS
        )
        context["can_manage_documents"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVERS_MANAGE_DOCUMENTS
        )
        context["can_assign_vehicle"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVERS_ASSIGN_VEHICLE
        )
        context["can_assign_carrier"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVERS_ASSIGN_CARRIER
        )
        context["compliance"] = evaluate_entity_compliance(
            entity_type=EntityType.DRIVER,
            documents=self.object.documents.all(),
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:8]
        from src.drivers.application.route_intent_services import get_active_route_intents_for_driver

        context["active_route_intents"] = get_active_route_intents_for_driver(self.object)
        context["can_manage_route_intents"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVER_ROUTE_INTENTS_CREATE
        )
        context["driver"] = self.object
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not user_has_backoffice_permission(request.user, PermissionCode.DRIVERS_APPROVE):
            raise PermissionDenied
        action = request.POST.get("action", "").strip()
        if action == "start_review":
            start_driver_review(self.object, actor=request.user)
        elif action == "approve":
            approve_driver(self.object, actor=request.user)
        elif action == "suspend":
            suspend_driver(self.object, actor=request.user, reason=request.POST.get("reason", ""))
        else:
            raise PermissionDenied
        return redirect("backoffice:driver_detail", pk=self.object.pk)


class DriverCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/drivers/form.html"
    permission_code = PermissionCode.DRIVERS_CREATE
    active_menu = "drivers"
    page_title = "Novo Motorista"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Motoristas", reverse_lazy("backoffice:drivers")),
        ("Novo Motorista", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = DriverForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = DriverForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                driver = register_driver(data=DriverData(**form.cleaned_data), actor=request.user)
                return redirect("backoffice:driver_detail", pk=driver.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class DriverUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/drivers/form.html"
    permission_code = PermissionCode.DRIVERS_UPDATE
    active_menu = "drivers"
    page_title = "Editar Motorista"

    def get_object(self):
        queryset = scoped_driver_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        driver = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Motoristas", reverse_lazy("backoffice:drivers")),
            (driver.full_name, reverse_lazy("backoffice:driver_detail", args=[driver.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        driver = self.get_object()
        if "form" not in context:
            context["form"] = DriverForm(instance=driver, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        driver = self.get_object()
        form = DriverForm(request.POST, instance=driver, user=request.user)
        if form.is_valid():
            try:
                changes = {
                    key: value
                    for key, value in form.cleaned_data.items()
                    if key not in {"organization", "user"}
                }
                update_driver(driver, actor=request.user, **changes)
                return redirect("backoffice:driver_detail", pk=driver.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class DriverStatusChangeView(BackofficePermissionMixin, TemplateView):
    permission_code = PermissionCode.DRIVERS_CHANGE_STATUS

    def post(self, request, *args, **kwargs):
        queryset = scoped_driver_queryset(request.user, self.permission_code)
        driver = get_object_or_404(queryset, pk=kwargs["pk"])
        status = request.POST.get("status", "").strip()
        if status in [value.value for value in DriverStatus]:
            change_driver_status(
                driver,
                status=DriverStatus(status),
                actor=request.user,
                reason=request.POST.get("reason", ""),
            )
        return redirect("backoffice:driver_detail", pk=driver.pk)


class VehicleForm(forms.ModelForm):
    refrigeration_unit_manufacturer = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Fabricante"}),
    )
    refrigeration_unit_model = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Modelo"}),
    )
    temperature_min_c = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=5,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    temperature_max_c = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=5,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    default_setpoint_c = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=5,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    refrigeration_control_type = forms.ChoiceField(
        required=False,
        choices=[("", "Selecione")]
        + [(value.value, value.value) for value in RefrigerationControlType],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    refrigeration_last_maintenance_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    refrigeration_next_maintenance_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    class Meta:
        model = Vehicle
        fields = [
            "organization",
            "plate",
            "renavam",
            "chassis",
            "vehicle_type",
            "body_type",
            "cargo_profile",
            "ownership_type",
            "brand",
            "model",
            "year",
            "model_year",
            "color",
            "state",
            "capacity_weight_kg",
            "gross_weight_kg",
            "capacity_volume_m3",
            "max_length_m",
            "max_width_m",
            "max_height_m",
            "odometer_km",
            "refrigerated",
            "closed_box",
            "open_body",
            "tail_lift",
            "helper_available",
            "hazardous_compatible",
            "status",
            "operational_status",
        ]
        widgets = {
            "organization": forms.Select(attrs={"class": "form-control"}),
            "plate": forms.TextInput(attrs={"class": "form-control", "placeholder": "ABC1D23"}),
            "renavam": forms.TextInput(attrs={"class": "form-control"}),
            "chassis": forms.TextInput(attrs={"class": "form-control"}),
            "vehicle_type": forms.Select(attrs={"class": "form-control"}),
            "body_type": forms.Select(attrs={"class": "form-control"}),
            "cargo_profile": forms.Select(attrs={"class": "form-control"}),
            "ownership_type": forms.Select(attrs={"class": "form-control"}),
            "brand": forms.TextInput(attrs={"class": "form-control"}),
            "model": forms.TextInput(attrs={"class": "form-control"}),
            "year": forms.NumberInput(attrs={"class": "form-control"}),
            "model_year": forms.NumberInput(attrs={"class": "form-control"}),
            "color": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control", "maxlength": 2}),
            "capacity_weight_kg": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "gross_weight_kg": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "capacity_volume_m3": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "max_length_m": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "max_width_m": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "max_height_m": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "odometer_km": forms.NumberInput(attrs={"class": "form-control"}),
            "refrigerated": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "closed_box": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "open_body": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "tail_lift": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "helper_available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "hazardous_compatible": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "operational_status": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["organization"].queryset = scoped_organization_queryset(
                user, PermissionCode.VEHICLES_VIEW
            )
        if self.instance.pk and hasattr(self.instance, "refrigeration_profile"):
            profile = self.instance.refrigeration_profile
            self.fields["refrigeration_unit_manufacturer"].initial = profile.unit_manufacturer
            self.fields["refrigeration_unit_model"].initial = profile.unit_model
            self.fields["temperature_min_c"].initial = profile.temperature_min_c
            self.fields["temperature_max_c"].initial = profile.temperature_max_c
            self.fields["default_setpoint_c"].initial = profile.default_setpoint_c
            self.fields["refrigeration_control_type"].initial = profile.control_type
            self.fields[
                "refrigeration_last_maintenance_date"
            ].initial = profile.last_maintenance_date
            self.fields[
                "refrigeration_next_maintenance_date"
            ].initial = profile.next_maintenance_date

    def clean(self):
        cleaned = super().clean()
        cargo_profile = cleaned.get("cargo_profile")
        requires_refrigeration = cargo_profile in {
            VehicleCargoProfile.REFRIGERATED_CARGO,
            VehicleCargoProfile.BOTH,
        }
        has_min = cleaned.get("temperature_min_c") is not None
        has_max = cleaned.get("temperature_max_c") is not None
        if requires_refrigeration and (not has_min or not has_max):
            self.add_error(
                "temperature_min_c",
                "Informe faixa térmica para veículos refrigerados ou mistos.",
            )
        if not requires_refrigeration:
            cleaned["temperature_min_c"] = None
            cleaned["temperature_max_c"] = None
            cleaned["default_setpoint_c"] = None
            cleaned["refrigeration_control_type"] = ""
            cleaned["refrigeration_unit_manufacturer"] = ""
            cleaned["refrigeration_unit_model"] = ""
            cleaned["refrigeration_last_maintenance_date"] = None
            cleaned["refrigeration_next_maintenance_date"] = None
        return cleaned


class VehicleListView(FilteredListView):
    template_name = "backoffice/pages/vehicles/list.html"
    context_object_name = "vehicles"
    permission_code = PermissionCode.VEHICLES_VIEW
    active_menu = "vehicles"
    page_title = "Veículos"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Veículos", None))

    def get_queryset(self):
        queryset = (
            scoped_vehicle_queryset(self.request.user, self.permission_code)
            .select_related("organization", "refrigeration_profile")
            .prefetch_related("driver_assignments__driver", "carrier_links__carrier")
            .annotate(
                active_driver_count=Count(
                    "driver_assignments",
                    filter=django_models.Q(driver_assignments__active=True),
                    distinct=True,
                ),
                active_carrier_count=Count(
                    "carrier_links",
                    filter=django_models.Q(carrier_links__active=True),
                    distinct=True,
                ),
            )
        )
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        operational_status = self.request.GET.get("operational_status", "").strip()
        vehicle_type = self.request.GET.get("vehicle_type", "").strip()
        body_type = self.request.GET.get("body_type", "").strip()
        cargo_profile = self.request.GET.get("cargo_profile", "").strip()
        carrier_id = self.request.GET.get("carrier", "").strip()
        driver_id = self.request.GET.get("driver", "").strip()
        state = self.request.GET.get("state", "").strip().upper()

        if query:
            queryset = queryset.filter(
                django_models.Q(plate__icontains=query.upper())
                | django_models.Q(renavam__icontains=query)
                | django_models.Q(brand__icontains=query)
                | django_models.Q(model__icontains=query)
                | django_models.Q(carrier_links__carrier__trade_name__icontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        if operational_status:
            queryset = queryset.filter(operational_status=operational_status)
        if vehicle_type:
            queryset = queryset.filter(vehicle_type=vehicle_type)
        if body_type:
            queryset = queryset.filter(body_type=body_type)
        if cargo_profile:
            queryset = queryset.filter(cargo_profile=cargo_profile)
        if carrier_id:
            queryset = queryset.filter(
                carrier_links__active=True,
                carrier_links__carrier_id=carrier_id,
            )
        if driver_id:
            queryset = queryset.filter(
                driver_assignments__active=True,
                driver_assignments__driver_id=driver_id,
            )
        if state:
            queryset = queryset.filter(state=state)
        return queryset.order_by("plate").distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = scoped_vehicle_queryset(self.request.user, self.permission_code)
        context["vehicle_statuses"] = list(VehicleStatus)
        context["operational_statuses"] = list(VehicleOperationalStatus)
        context["vehicle_types"] = list(VehicleType)
        context["vehicle_body_types"] = list(VehicleBodyType)
        context["vehicle_cargo_profiles"] = list(VehicleCargoProfile)
        context["carriers"] = scoped_carrier_queryset(
            self.request.user, PermissionCode.CARRIERS_VIEW
        ).order_by("trade_name")
        context["drivers"] = scoped_driver_queryset(
            self.request.user, PermissionCode.DRIVERS_VIEW
        ).order_by("full_name")
        context["can_create_vehicle"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.VEHICLES_CREATE
        )
        context["kpis"] = {
            "total": base_qs.count(),
            "active": base_qs.filter(status=VehicleStatus.ACTIVE).count(),
            "available": base_qs.filter(
                operational_status=VehicleOperationalStatus.AVAILABLE
            ).count(),
            "maintenance": base_qs.filter(
                operational_status=VehicleOperationalStatus.MAINTENANCE
            ).count(),
            "dry": base_qs.filter(cargo_profile=VehicleCargoProfile.DRY_CARGO).count(),
            "refrigerated": base_qs.filter(
                cargo_profile__in=[
                    VehicleCargoProfile.REFRIGERATED_CARGO,
                    VehicleCargoProfile.BOTH,
                ]
            ).count(),
        }
        return context


class VehicleDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/vehicles/detail.html"
    context_object_name = "vehicle"
    permission_code = PermissionCode.VEHICLES_VIEW
    active_menu = "vehicles"
    page_title = "Veículo"

    def get_queryset(self):
        return (
            scoped_vehicle_queryset(self.request.user, self.permission_code)
            .select_related("organization", "refrigeration_profile")
            .prefetch_related(
                "driver_assignments__driver",
                "carrier_links__carrier__organization",
                "documents",
            )
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Veículos", reverse_lazy("backoffice:vehicles")),
            (self.object.plate, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_update_vehicle"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.VEHICLES_UPDATE
        )
        context["can_change_vehicle_status"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.VEHICLES_CHANGE_STATUS
        )
        context["can_manage_vehicle_refrigeration"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.VEHICLES_MANAGE_REFRIGERATION
        )
        context["can_manage_documents"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.VEHICLES_MANAGE_DOCUMENTS
        )
        context["compliance"] = evaluate_entity_compliance(
            entity_type=EntityType.VEHICLE,
            documents=self.object.documents.all(),
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:8]
        from src.drivers.application.route_intent_services import get_active_route_intents_for_vehicle

        context["active_route_intents"] = get_active_route_intents_for_vehicle(self.object)
        context["can_manage_route_intents"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DRIVER_ROUTE_INTENTS_CREATE
        )
        context["driver"] = None
        context["vehicle"] = self.object
        return context


class VehicleCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/vehicles/form.html"
    permission_code = PermissionCode.VEHICLES_CREATE
    active_menu = "vehicles"
    page_title = "Novo Veículo"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Veículos", reverse_lazy("backoffice:vehicles")),
        ("Novo Veículo", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = VehicleForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = VehicleForm(request.POST, user=request.user)
        if form.is_valid():
            data = VehicleData(
                **{
                    key: value
                    for key, value in form.cleaned_data.items()
                    if key in VehicleData.__annotations__
                }
            )
            refrigeration_data = None
            if data.cargo_profile in {
                VehicleCargoProfile.REFRIGERATED_CARGO,
                VehicleCargoProfile.BOTH,
            }:
                refrigeration_data = RefrigerationProfileData(
                    unit_manufacturer=form.cleaned_data["refrigeration_unit_manufacturer"],
                    unit_model=form.cleaned_data["refrigeration_unit_model"],
                    temperature_min_c=form.cleaned_data["temperature_min_c"],
                    temperature_max_c=form.cleaned_data["temperature_max_c"],
                    default_setpoint_c=form.cleaned_data["default_setpoint_c"],
                    control_type=RefrigerationControlType(
                        form.cleaned_data["refrigeration_control_type"]
                    )
                    if form.cleaned_data["refrigeration_control_type"]
                    else RefrigerationControlType.DIGITAL,
                    last_maintenance_date=form.cleaned_data["refrigeration_last_maintenance_date"],
                    next_maintenance_date=form.cleaned_data["refrigeration_next_maintenance_date"],
                )
            try:
                vehicle = register_vehicle(
                    data=data,
                    refrigeration_data=refrigeration_data,
                    actor=request.user,
                )
                return redirect("backoffice:vehicle_detail", pk=vehicle.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class VehicleUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/vehicles/form.html"
    permission_code = PermissionCode.VEHICLES_UPDATE
    active_menu = "vehicles"
    page_title = "Editar Veículo"

    def get_object(self):
        return get_object_or_404(
            scoped_vehicle_queryset(self.request.user, self.permission_code),
            pk=self.kwargs["pk"],
        )

    def get_breadcrumbs(self):
        vehicle = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Veículos", reverse_lazy("backoffice:vehicles")),
            (vehicle.plate, reverse_lazy("backoffice:vehicle_detail", args=[vehicle.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehicle = self.get_object()
        if "form" not in context:
            context["form"] = VehicleForm(instance=vehicle, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        vehicle = self.get_object()
        form = VehicleForm(request.POST, instance=vehicle, user=request.user)
        if form.is_valid():
            try:
                vehicle_changes = {
                    key: value
                    for key, value in form.cleaned_data.items()
                    if key
                    in {
                        "plate",
                        "renavam",
                        "chassis",
                        "vehicle_type",
                        "body_type",
                        "cargo_profile",
                        "ownership_type",
                        "brand",
                        "model",
                        "year",
                        "model_year",
                        "color",
                        "state",
                        "capacity_weight_kg",
                        "gross_weight_kg",
                        "capacity_volume_m3",
                        "max_length_m",
                        "max_width_m",
                        "max_height_m",
                        "odometer_km",
                        "refrigerated",
                        "closed_box",
                        "open_body",
                        "tail_lift",
                        "helper_available",
                        "hazardous_compatible",
                        "status",
                        "operational_status",
                    }
                }
                update_vehicle(vehicle, actor=request.user, **vehicle_changes)
                if form.cleaned_data["cargo_profile"] in {
                    VehicleCargoProfile.REFRIGERATED_CARGO,
                    VehicleCargoProfile.BOTH,
                }:
                    upsert_refrigeration_profile(
                        vehicle=vehicle,
                        data=RefrigerationProfileData(
                            unit_manufacturer=form.cleaned_data["refrigeration_unit_manufacturer"],
                            unit_model=form.cleaned_data["refrigeration_unit_model"],
                            temperature_min_c=form.cleaned_data["temperature_min_c"],
                            temperature_max_c=form.cleaned_data["temperature_max_c"],
                            default_setpoint_c=form.cleaned_data["default_setpoint_c"],
                            control_type=RefrigerationControlType(
                                form.cleaned_data["refrigeration_control_type"]
                            )
                            if form.cleaned_data["refrigeration_control_type"]
                            else RefrigerationControlType.DIGITAL,
                            last_maintenance_date=form.cleaned_data[
                                "refrigeration_last_maintenance_date"
                            ],
                            next_maintenance_date=form.cleaned_data[
                                "refrigeration_next_maintenance_date"
                            ],
                        ),
                        actor=request.user,
                    )
                elif hasattr(vehicle, "refrigeration_profile"):
                    vehicle.refrigeration_profile.delete()
                return redirect("backoffice:vehicle_detail", pk=vehicle.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class VehicleStatusChangeView(BackofficePermissionMixin, TemplateView):
    permission_code = PermissionCode.VEHICLES_CHANGE_STATUS

    def post(self, request, *args, **kwargs):
        vehicle = get_object_or_404(
            scoped_vehicle_queryset(request.user, self.permission_code),
            pk=kwargs["pk"],
        )
        status = request.POST.get("status", "").strip()
        operational_status = request.POST.get("operational_status", "").strip()
        if status and status in [value.value for value in VehicleStatus]:
            change_vehicle_status(
                vehicle,
                status=VehicleStatus(status),
                actor=request.user,
                reason=request.POST.get("reason", ""),
            )
        if operational_status and operational_status in [
            value.value for value in VehicleOperationalStatus
        ]:
            change_vehicle_operational_status(
                vehicle,
                operational_status=VehicleOperationalStatus(operational_status),
                actor=request.user,
                reason=request.POST.get("reason", ""),
            )
        return redirect("backoffice:vehicle_detail", pk=vehicle.pk)


class BackofficeAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Usuário ou senha inválidos.",
        "inactive": "Usuário ou senha inválidos.",
    }


class BackofficeLoginView(LoginView):
    """Session login using Rotta's configured AUTH_USER_MODEL."""

    template_name = "backoffice/pages/login.html"
    authentication_form = BackofficeAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy("backoffice:dashboard")


class BackofficeLogoutView(LogoutView):
    next_page = reverse_lazy("backoffice:login")


class BackofficeForbiddenView(LoginRequiredMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/403.html"
    active_menu = ""
    page_title = "Acesso negado"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Acesso negado", None))


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "customer_type",
            "legal_name",
            "trade_name",
            "document_number",
            "state_registration",
            "municipal_registration",
            "email",
            "phone",
            "mobile_phone",
            "postal_code",
            "street",
            "number",
            "complement",
            "district",
            "city",
            "state",
            "country",
            "organization",
            "business_unit",
            "owner",
        ]
        widgets = {
            "customer_type": forms.Select(attrs={"class": "form-control"}),
            "legal_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Razão Social ou Nome Completo"}
            ),
            "trade_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nome Fantasia"}
            ),
            "document_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "CPF ou CNPJ"}
            ),
            "state_registration": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Inscrição Estadual"}
            ),
            "municipal_registration": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Inscrição Municipal"}
            ),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "E-mail"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Telefone"}),
            "mobile_phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Celular"}
            ),
            "postal_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "CEP"}),
            "street": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rua"}),
            "number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número"}),
            "complement": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Complemento"}
            ),
            "district": forms.TextInput(attrs={"class": "form-control", "placeholder": "Bairro"}),
            "city": forms.TextInput(attrs={"class": "form-control", "placeholder": "Cidade"}),
            "state": forms.TextInput(attrs={"class": "form-control", "placeholder": "UF"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.Select(attrs={"class": "form-control"}),
            "business_unit": forms.Select(attrs={"class": "form-control"}),
            "owner": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and not user_has_backoffice_permission(user, PermissionCode.CUSTOMERS_ASSIGN_OWNER):
            self.fields["owner"].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        instance = Customer(**cleaned_data)
        try:
            instance.clean()
        except ValidationError as e:
            if "document_number" in e.message_dict:
                self.add_error("document_number", e.message_dict["document_number"])
            else:
                self.add_error(None, e)
        return cleaned_data


class CustomerListView(FilteredListView):
    template_name = "backoffice/pages/customers/list.html"
    context_object_name = "customers"
    permission_code = PermissionCode.CUSTOMERS_VIEW
    active_menu = "customers"
    page_title = "Clientes"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Clientes", None))

    def get_queryset(self):
        queryset = scoped_customer_queryset(self.request.user, self.permission_code)
        queryset = queryset.select_related("organization", "owner", "business_unit")
        query = self.request.GET.get("q", "").strip()
        customer_type = self.request.GET.get("type", "").strip()
        status = self.request.GET.get("status", "").strip()
        if query:
            queryset = queryset.filter(
                django_models.Q(legal_name__icontains=query)
                | django_models.Q(trade_name__icontains=query)
                | django_models.Q(document_number__icontains=query)
                | django_models.Q(email__icontains=query)
            )
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customer_types"] = list(CustomerType)
        context["customer_statuses"] = list(CustomerStatus)
        context["can_create_customer"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CUSTOMERS_CREATE
        )
        return context


class CustomerDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/customers/detail.html"
    context_object_name = "customer"
    permission_code = PermissionCode.CUSTOMERS_VIEW
    active_menu = "customers"
    page_title = "Detalhe do Cliente"

    def get_queryset(self):
        return scoped_customer_queryset(self.request.user, self.permission_code).select_related(
            "organization", "business_unit", "owner"
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Clientes", reverse_lazy("backoffice:customers")),
            (self.object.legal_name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_change_status"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CUSTOMERS_CHANGE_STATUS
        )
        context["can_assign_owner"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CUSTOMERS_ASSIGN_OWNER
        )
        context["can_edit_customer"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CUSTOMERS_UPDATE
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:8]
        return context


class CustomerCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/customers/form.html"
    permission_code = PermissionCode.CUSTOMERS_CREATE
    active_menu = "customers"
    page_title = "Novo Cliente"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Clientes", reverse_lazy("backoffice:customers")),
        ("Novo Cliente", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = CustomerForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = CustomerForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                data = CustomerData(**form.cleaned_data)
                customer = register_customer(data=data, actor=request.user)
                return redirect("backoffice:customer_detail", pk=customer.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class CustomerUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/customers/form.html"
    permission_code = PermissionCode.CUSTOMERS_UPDATE
    active_menu = "customers"
    page_title = "Editar Cliente"

    def get_object(self):
        queryset = scoped_customer_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        obj = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Clientes", reverse_lazy("backoffice:customers")),
            (obj.legal_name, reverse_lazy("backoffice:customer_detail", args=[obj.id])),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        if "form" not in context:
            context["form"] = CustomerForm(instance=obj, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        customer = self.get_object()
        form = CustomerForm(request.POST, instance=customer, user=request.user)
        if form.is_valid():
            try:
                if "owner" in form.changed_data:
                    if not user_has_backoffice_permission(
                        request.user, PermissionCode.CUSTOMERS_ASSIGN_OWNER
                    ):
                        raise PermissionDenied
                changes = {k: v for k, v in form.cleaned_data.items() if k not in ["organization"]}
                update_customer(customer, actor=request.user, **changes)
                return redirect("backoffice:customer_detail", pk=customer.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class CustomerStatusChangeView(BackofficePermissionMixin, TemplateView):
    permission_code = PermissionCode.CUSTOMERS_CHANGE_STATUS

    def post(self, request, *args, **kwargs):
        queryset = scoped_customer_queryset(request.user, self.permission_code)
        customer = get_object_or_404(queryset, pk=kwargs["pk"])
        action = request.POST.get("action")
        if action in [status.value for status in CustomerStatus]:
            change_customer_status(customer, status=CustomerStatus(action), actor=request.user)
        return redirect("backoffice:customer_detail", pk=customer.pk)


class CarrierForm(forms.ModelForm):
    class Meta:
        model = CarrierProfile
        fields = [
            "tenant",
            "organization",
            "trade_name",
            "state_registration",
            "municipal_registration",
            "email",
            "phone",
            "mobile_phone",
            "site",
            "postal_code",
            "street",
            "number",
            "complement",
            "district",
            "city",
            "state",
            "country",
            "rntrc",
            "rntrc_category",
            "rntrc_expiration",
            "rntrc_status",
            "cargo_profile",
            "owner",
        ]
        widgets = {
            "tenant": forms.Select(attrs={"class": "form-control"}),
            "organization": forms.Select(attrs={"class": "form-control"}),
            "trade_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nome fantasia operacional"}
            ),
            "state_registration": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Inscrição Estadual"}
            ),
            "municipal_registration": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Inscrição Municipal"}
            ),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "E-mail"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Telefone"}),
            "mobile_phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Celular"}
            ),
            "site": forms.TextInput(attrs={"class": "form-control", "placeholder": "Site"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "CEP"}),
            "street": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rua"}),
            "number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Número"}),
            "complement": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Complemento"}
            ),
            "district": forms.TextInput(attrs={"class": "form-control", "placeholder": "Bairro"}),
            "city": forms.TextInput(attrs={"class": "form-control", "placeholder": "Cidade"}),
            "state": forms.TextInput(attrs={"class": "form-control", "placeholder": "UF"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "rntrc": forms.TextInput(attrs={"class": "form-control", "placeholder": "RNTRC"}),
            "rntrc_category": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Categoria RNTRC"}
            ),
            "rntrc_expiration": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
                format="%Y-%m-%d",
            ),
            "rntrc_status": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Situação RNTRC"}
            ),
            "cargo_profile": forms.Select(attrs={"class": "form-control"}),
            "owner": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            scoped_orgs = scoped_organization_queryset(user, PermissionCode.CARRIERS_VIEW)
            self.fields["tenant"].queryset = scoped_orgs
            self.fields["organization"].queryset = Organization.objects.all().order_by("name")
            self.fields["owner"].queryset = scoped_user_queryset(user, PermissionCode.USERS_VIEW)
            if not user_has_backoffice_permission(user, PermissionCode.CARRIERS_ASSIGN_OWNER):
                self.fields["owner"].disabled = True
            if self.instance.pk:
                self.fields["tenant"].disabled = True
                self.fields["organization"].disabled = True


class CarrierListView(FilteredListView):
    template_name = "backoffice/pages/carriers/list.html"
    context_object_name = "carriers"
    permission_code = PermissionCode.CARRIERS_VIEW
    active_menu = "carriers"
    page_title = "Transportadoras"
    breadcrumbs = (("Dashboard", reverse_lazy("backoffice:dashboard")), ("Transportadoras", None))

    def get_queryset(self):
        queryset = (
            scoped_carrier_queryset(self.request.user, self.permission_code)
            .select_related("organization", "tenant", "owner")
            .annotate(
                drivers_count=Count(
                    "driver_links",
                    filter=django_models.Q(driver_links__active=True),
                    distinct=True,
                ),
                vehicles_count=Count(
                    "vehicle_links",
                    filter=django_models.Q(vehicle_links__active=True),
                    distinct=True,
                ),
            )
        )
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        cargo_profile = self.request.GET.get("cargo_profile", "").strip()
        state = self.request.GET.get("state", "").strip().upper()
        owner = self.request.GET.get("owner", "").strip()
        if query:
            queryset = queryset.filter(
                django_models.Q(trade_name__icontains=query)
                | django_models.Q(organization__name__icontains=query)
                | django_models.Q(organization__legal_name__icontains=query)
                | django_models.Q(organization__document__icontains=query)
                | django_models.Q(rntrc__icontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        if cargo_profile:
            queryset = queryset.filter(cargo_profile=cargo_profile)
        if state:
            queryset = queryset.filter(state=state)
        if owner:
            queryset = queryset.filter(owner_id=owner)
        return queryset.order_by("trade_name", "organization__name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = scoped_carrier_queryset(self.request.user, self.permission_code)
        context["carrier_statuses"] = list(CarrierStatus)
        context["carrier_cargo_profiles"] = list(CarrierCargoProfile)
        context["owners"] = scoped_user_queryset(self.request.user, PermissionCode.USERS_VIEW)
        context["can_create_carrier"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CARRIERS_CREATE
        )
        context["kpis"] = {
            "total": base_qs.count(),
            "active": base_qs.filter(status=CarrierStatus.ACTIVE).count(),
            "pending": base_qs.filter(status=CarrierStatus.PENDING_APPROVAL).count(),
            "suspended_or_blocked": base_qs.filter(
                status__in=[CarrierStatus.SUSPENDED, CarrierStatus.BLOCKED]
            ).count(),
            "dry_cargo": base_qs.filter(
                cargo_profile__in=[CarrierCargoProfile.DRY_CARGO, CarrierCargoProfile.BOTH]
            ).count(),
            "refrigerated_cargo": base_qs.filter(
                cargo_profile__in=[
                    CarrierCargoProfile.REFRIGERATED_CARGO,
                    CarrierCargoProfile.BOTH,
                ]
            ).count(),
        }
        return context


class CarrierDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/carriers/detail.html"
    context_object_name = "carrier"
    permission_code = PermissionCode.CARRIERS_VIEW
    active_menu = "carriers"
    page_title = "Detalhe da Transportadora"

    def get_queryset(self):
        return (
            scoped_carrier_queryset(self.request.user, self.permission_code)
            .select_related("organization", "tenant", "owner")
            .prefetch_related("driver_links__driver", "vehicle_links__vehicle", "documents")
        )

    def get_breadcrumbs(self):
        carrier = self.object
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Transportadoras", reverse_lazy("backoffice:carriers")),
            (carrier.trade_name or carrier.organization.name, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_change_status"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CARRIERS_CHANGE_STATUS
        )
        context["can_edit_carrier"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CARRIERS_UPDATE
        )
        context["can_manage_drivers"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CARRIERS_MANAGE_DRIVERS
        )
        context["can_manage_vehicles"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CARRIERS_MANAGE_VEHICLES
        )
        context["can_manage_documents"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.CARRIERS_MANAGE_DOCUMENTS
        )
        context["compliance"] = evaluate_entity_compliance(
            entity_type=EntityType.CARRIER,
            documents=self.object.documents.all(),
        )
        context["audit_logs"] = AuditLog.objects.filter(
            target_id=str(self.object.id)
        ).select_related("actor", "organization")[:8]
        return context


class CarrierCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/carriers/form.html"
    permission_code = PermissionCode.CARRIERS_CREATE
    active_menu = "carriers"
    page_title = "Nova Transportadora"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Transportadoras", reverse_lazy("backoffice:carriers")),
        ("Nova Transportadora", None),
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = CarrierForm(user=self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        form = CarrierForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                data = CarrierData(**form.cleaned_data)
                carrier = create_carrier(data=data, actor=request.user)
                return redirect("backoffice:carrier_detail", pk=carrier.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class CarrierUpdateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/carriers/form.html"
    permission_code = PermissionCode.CARRIERS_UPDATE
    active_menu = "carriers"
    page_title = "Editar Transportadora"

    def get_object(self):
        queryset = scoped_carrier_queryset(self.request.user, self.permission_code)
        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_breadcrumbs(self):
        carrier = self.get_object()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Transportadoras", reverse_lazy("backoffice:carriers")),
            (
                carrier.trade_name or carrier.organization.name,
                reverse_lazy("backoffice:carrier_detail", args=[carrier.id]),
            ),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        carrier = self.get_object()
        if "form" not in context:
            context["form"] = CarrierForm(instance=carrier, user=self.request.user)
        context["is_edit"] = True
        return context

    def post(self, request, *args, **kwargs):
        carrier = self.get_object()
        form = CarrierForm(request.POST, instance=carrier, user=request.user)
        if form.is_valid():
            try:
                if "owner" in form.changed_data and not user_has_backoffice_permission(
                    request.user, PermissionCode.CARRIERS_ASSIGN_OWNER
                ):
                    raise PermissionDenied
                changes = {
                    key: value
                    for key, value in form.cleaned_data.items()
                    if key not in ["tenant", "organization"]
                }
                update_carrier(carrier, actor=request.user, **changes)
                return redirect("backoffice:carrier_detail", pk=carrier.pk)
            except ValidationError as e:
                form.add_error(None, e)
        return render(request, self.template_name, self.get_context_data(form=form))


class CarrierStatusChangeView(BackofficePermissionMixin, TemplateView):
    permission_code = PermissionCode.CARRIERS_CHANGE_STATUS

    def post(self, request, *args, **kwargs):
        queryset = scoped_carrier_queryset(request.user, self.permission_code)
        carrier = get_object_or_404(queryset, pk=kwargs["pk"])
        action = request.POST.get("action")
        if action in [status.value for status in CarrierStatus]:
            change_carrier_status(carrier, status=CarrierStatus(action), actor=request.user)
        return redirect("backoffice:carrier_detail", pk=carrier.pk)


def backoffice_permission_denied(request, exception=None):
    if request.path.startswith("/app/"):
        return render(
            request,
            "backoffice/pages/403.html",
            {
                "active_menu": "",
                "page_title": "Acesso negado",
                "breadcrumbs": (
                    ("Dashboard", reverse_lazy("backoffice:dashboard")),
                    ("Acesso negado", None),
                ),
            },
            status=403,
        )
    return default_views.permission_denied(request, exception)
