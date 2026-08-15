from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from src.compliance.application.expiration import (
    document_validity_status,
    expiration_window_filter,
    expired_filter,
)
from src.compliance.application.services import UnifiedDocument, unified_document_from_instance
from src.compliance.domain.enums import DocumentStatus, EntityType


@dataclass(frozen=True)
class DocumentFilters:
    q: str = ""
    entity_type: str = ""
    document_type: str = ""
    status: str = ""
    validity: str = ""
    organization_id: str = ""
    reviewer_id: str = ""


def _apply_common_filters(queryset, *, filters: DocumentFilters, entity_type: EntityType):
    if filters.document_type:
        queryset = queryset.filter(document_type=filters.document_type)
    if filters.status:
        queryset = queryset.filter(status=filters.status)
    if filters.reviewer_id:
        queryset = queryset.filter(reviewed_by_id=filters.reviewer_id)
    if filters.validity == "expired":
        queryset = queryset.filter(expired_filter())
    elif filters.validity == "expiring_30":
        queryset = queryset.filter(expiration_window_filter(days=30))
    elif filters.validity == "expiring_15":
        queryset = queryset.filter(expiration_window_filter(days=15))
    elif filters.validity == "expiring_7":
        queryset = queryset.filter(expiration_window_filter(days=7))
    elif filters.validity == "valid":
        queryset = (
            queryset.exclude(expired_filter())
            .exclude(expiration_window_filter(days=30))
            .exclude(expiration_date__isnull=True)
        )
    if filters.q:
        if entity_type == EntityType.DRIVER:
            queryset = queryset.filter(
                Q(driver__full_name__icontains=filters.q)
                | Q(original_filename__icontains=filters.q)
                | Q(document_type__icontains=filters.q)
            )
        elif entity_type == EntityType.VEHICLE:
            queryset = queryset.filter(
                Q(vehicle__plate__icontains=filters.q)
                | Q(original_filename__icontains=filters.q)
                | Q(document_type__icontains=filters.q)
            )
        else:
            queryset = queryset.filter(
                Q(carrier__trade_name__icontains=filters.q)
                | Q(carrier__organization__name__icontains=filters.q)
                | Q(original_filename__icontains=filters.q)
                | Q(document_type__icontains=filters.q)
            )
    return queryset


def collect_unified_documents(
    *,
    driver_documents_qs,
    vehicle_documents_qs,
    carrier_documents_qs,
    filters: DocumentFilters,
) -> list[UnifiedDocument]:
    records: list[UnifiedDocument] = []

    if not filters.entity_type or filters.entity_type == EntityType.DRIVER.value:
        driver_qs = _apply_common_filters(
            driver_documents_qs.select_related("driver", "reviewed_by"),
            filters=filters,
            entity_type=EntityType.DRIVER,
        )
        if filters.organization_id:
            driver_qs = driver_qs.filter(driver__organization_id=filters.organization_id)
        records.extend(
            unified_document_from_instance(document, EntityType.DRIVER) for document in driver_qs
        )

    if not filters.entity_type or filters.entity_type == EntityType.VEHICLE.value:
        vehicle_qs = _apply_common_filters(
            vehicle_documents_qs.select_related("vehicle", "reviewed_by"),
            filters=filters,
            entity_type=EntityType.VEHICLE,
        )
        if filters.organization_id:
            vehicle_qs = vehicle_qs.filter(vehicle__organization_id=filters.organization_id)
        records.extend(
            unified_document_from_instance(document, EntityType.VEHICLE) for document in vehicle_qs
        )

    if not filters.entity_type or filters.entity_type == EntityType.CARRIER.value:
        carrier_qs = _apply_common_filters(
            carrier_documents_qs.select_related("carrier", "carrier__organization", "reviewed_by"),
            filters=filters,
            entity_type=EntityType.CARRIER,
        )
        if filters.organization_id:
            carrier_qs = carrier_qs.filter(carrier__tenant_id=filters.organization_id)
        records.extend(
            unified_document_from_instance(document, EntityType.CARRIER) for document in carrier_qs
        )

    records.sort(key=lambda item: item.created_at, reverse=True)
    return records


def document_kpis(
    *, driver_documents_qs, vehicle_documents_qs, carrier_documents_qs
) -> dict[str, int]:
    all_status_pending = DocumentStatus.PENDING.value
    all_status_under_review = DocumentStatus.UNDER_REVIEW.value
    all_status_approved = DocumentStatus.APPROVED.value
    all_status_rejected = DocumentStatus.REJECTED.value
    all_status_expired = DocumentStatus.EXPIRED.value

    combined = []
    for queryset in (driver_documents_qs, vehicle_documents_qs, carrier_documents_qs):
        combined.append(queryset)

    def count_all(**filters):
        return sum(queryset.filter(**filters).count() for queryset in combined)

    def count_expiring(days: int):
        return sum(
            queryset.filter(expiration_window_filter(days=days))
            .exclude(status__in=[DocumentStatus.EXPIRED.value, DocumentStatus.REPLACED.value])
            .count()
            for queryset in combined
        )

    def count_expired_by_date():
        return sum(
            queryset.filter(expired_filter()).exclude(status=DocumentStatus.REPLACED.value).count()
            for queryset in combined
        )

    return {
        "total": sum(queryset.count() for queryset in combined),
        "pending_review": count_all(status=all_status_under_review),
        "pending": count_all(status=all_status_pending),
        "approved": count_all(status=all_status_approved),
        "rejected": count_all(status=all_status_rejected),
        "expired": count_all(status=all_status_expired) + count_expired_by_date(),
        "expiring_30": count_expiring(30),
        "expiring_15": count_expiring(15),
        "expiring_7": count_expiring(7),
    }


def validity_label(document) -> str:
    return document_validity_status(expiration_date=document.expiration_date).value
