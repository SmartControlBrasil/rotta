from __future__ import annotations

from typing import Any

from django.utils import timezone

from src.freights.infrastructure.django.models import FreightOffer, MarketplaceEvent
from src.freights.domain.matching_enums import MarketplaceEventType


def record_marketplace_event(
    *,
    offer: FreightOffer,
    event_type: MarketplaceEventType,
    actor=None,
    carrier=None,
    driver=None,
    metadata: dict[str, Any] | None = None,
) -> MarketplaceEvent:
    return MarketplaceEvent.objects.create(
        organization=offer.organization,
        offer=offer,
        event_type=event_type.value,
        actor=actor,
        carrier=carrier,
        driver=driver,
        metadata=metadata or {},
    )


def record_offer_opened(*, offer: FreightOffer, actor=None) -> MarketplaceEvent:
    return record_marketplace_event(
        offer=offer,
        event_type=MarketplaceEventType.OFFER_OPENED,
        actor=actor,
        metadata={"opened_at": timezone.now().isoformat()},
    )
