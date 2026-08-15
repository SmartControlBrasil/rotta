from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from src.compliance.domain.enums import DocumentStatus, DocumentValidityStatus


def document_validity_status(
    *, expiration_date: date | None, reference_date: date | None = None
) -> DocumentValidityStatus:
    if expiration_date is None:
        return DocumentValidityStatus.NO_EXPIRATION
    today = reference_date or timezone.localdate()
    if expiration_date < today:
        return DocumentValidityStatus.EXPIRED
    if expiration_date <= today + timedelta(days=30):
        return DocumentValidityStatus.EXPIRING
    return DocumentValidityStatus.VALID


def is_document_expired(
    *, expiration_date: date | None, reference_date: date | None = None
) -> bool:
    if expiration_date is None:
        return False
    today = reference_date or timezone.localdate()
    return expiration_date < today


def expiration_window_filter(*, days: int, reference_date: date | None = None) -> Q:
    today = reference_date or timezone.localdate()
    upper = today + timedelta(days=days)
    return Q(expiration_date__gte=today, expiration_date__lte=upper)


def expired_filter(*, reference_date: date | None = None) -> Q:
    today = reference_date or timezone.localdate()
    return Q(expiration_date__lt=today)


def filter_expiring_documents(queryset: QuerySet, *, days: int) -> QuerySet:
    return queryset.filter(expiration_window_filter(days=days)).exclude(
        status__in=[DocumentStatus.EXPIRED.value, DocumentStatus.REPLACED.value]
    )


def filter_expired_documents(queryset: QuerySet) -> QuerySet:
    return queryset.filter(expired_filter()).exclude(status=DocumentStatus.REPLACED.value)
