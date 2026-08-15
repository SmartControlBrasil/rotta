from src.freights.domain.offer_enums import FreightOfferStatus

ALLOWED_OFFER_STATUS_TRANSITIONS: dict[FreightOfferStatus, frozenset[FreightOfferStatus]] = {
    FreightOfferStatus.DRAFT: frozenset({FreightOfferStatus.READY, FreightOfferStatus.CANCELLED}),
    FreightOfferStatus.READY: frozenset(
        {FreightOfferStatus.PUBLISHED, FreightOfferStatus.CANCELLED}
    ),
    FreightOfferStatus.PUBLISHED: frozenset(
        {
            FreightOfferStatus.PAUSED,
            FreightOfferStatus.CANCELLED,
            FreightOfferStatus.EXPIRED,
            FreightOfferStatus.CLOSED,
        }
    ),
    FreightOfferStatus.PAUSED: frozenset(
        {
            FreightOfferStatus.PUBLISHED,
            FreightOfferStatus.CANCELLED,
            FreightOfferStatus.CLOSED,
        }
    ),
    FreightOfferStatus.EXPIRED: frozenset(),
    FreightOfferStatus.CANCELLED: frozenset(),
    FreightOfferStatus.CLOSED: frozenset(),
}


def can_transition_offer(
    *,
    current: FreightOfferStatus,
    target: FreightOfferStatus,
) -> bool:
    return target in ALLOWED_OFFER_STATUS_TRANSITIONS.get(current, frozenset())


QUOTE_STATUSES_ELIGIBLE_FOR_OFFER = frozenset({"APPROVED", "SENT"})
