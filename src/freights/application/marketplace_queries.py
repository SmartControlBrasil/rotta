from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.eligibility import is_entity_eligible_for_offer
from src.freights.application.offer_services import apply_offer_expiration_if_needed
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.infrastructure.django.models import FreightOffer


def _base_published_queryset() -> QuerySet[FreightOffer]:
    now = timezone.now()
    return FreightOffer.objects.filter(
        status=FreightOfferStatus.PUBLISHED.value,
        expires_at__gt=now,
    )


def _audience_filter(
    queryset: QuerySet[FreightOffer],
    *,
    carrier: CarrierProfile | None,
    driver: Driver | None,
) -> QuerySet[FreightOffer]:
    if carrier is not None:
        return queryset.filter(
            Q(audience__in=[FreightOfferAudience.CARRIERS.value, FreightOfferAudience.BOTH.value])
            | Q(
                audience=FreightOfferAudience.PRIVATE.value,
                targets__carrier=carrier,
            )
        ).distinct()
    if driver is not None:
        return queryset.filter(
            Q(audience__in=[FreightOfferAudience.DRIVERS.value, FreightOfferAudience.BOTH.value])
            | Q(
                audience=FreightOfferAudience.PRIVATE.value,
                targets__driver=driver,
            )
        ).distinct()
    return queryset.exclude(audience=FreightOfferAudience.PRIVATE.value)


def published_offer_queryset_for_actor(
    *,
    organization_id,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
) -> QuerySet[FreightOffer]:
    """Marketplace visibility — não usar filter(status=PUBLISHED) isolado."""
    if carrier is None and driver is None:
        return FreightOffer.objects.none()
    if carrier is not None and driver is not None:
        return FreightOffer.objects.none()

    queryset = (
        _base_published_queryset()
        .filter(organization_id=organization_id)
        .prefetch_related("targets", "freight_request__cargo")
    )
    queryset = _audience_filter(queryset, carrier=carrier, driver=driver)

    eligible_ids: list = []
    entity_carrier = carrier
    entity_driver = driver
    for offer in queryset:
        offer = apply_offer_expiration_if_needed(offer)
        if offer.status != FreightOfferStatus.PUBLISHED.value:
            continue
        if offer.audience == FreightOfferAudience.PRIVATE.value and not offer.targets.exists():
            continue
        if is_entity_eligible_for_offer(
            offer=offer,
            carrier=entity_carrier,
            driver=entity_driver,
        ):
            eligible_ids.append(offer.id)

    return FreightOffer.objects.filter(id__in=eligible_ids).order_by("-published_at")
