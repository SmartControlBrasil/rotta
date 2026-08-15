from src.freights.domain.quote_enums import FreightQuoteStatus

ALLOWED_QUOTE_STATUS_TRANSITIONS: dict[FreightQuoteStatus, frozenset[FreightQuoteStatus]] = {
    FreightQuoteStatus.DRAFT: frozenset(
        {FreightQuoteStatus.UNDER_REVIEW, FreightQuoteStatus.CANCELLED}
    ),
    FreightQuoteStatus.CALCULATED: frozenset(
        {FreightQuoteStatus.UNDER_REVIEW, FreightQuoteStatus.CANCELLED}
    ),
    FreightQuoteStatus.UNDER_REVIEW: frozenset(
        {
            FreightQuoteStatus.APPROVED,
            FreightQuoteStatus.REJECTED,
            FreightQuoteStatus.CANCELLED,
        }
    ),
    FreightQuoteStatus.APPROVED: frozenset({FreightQuoteStatus.SENT, FreightQuoteStatus.CANCELLED}),
    FreightQuoteStatus.SENT: frozenset({FreightQuoteStatus.EXPIRED, FreightQuoteStatus.CANCELLED}),
    FreightQuoteStatus.REJECTED: frozenset({FreightQuoteStatus.CANCELLED}),
    FreightQuoteStatus.EXPIRED: frozenset(),
    FreightQuoteStatus.CANCELLED: frozenset(),
    FreightQuoteStatus.SUPERSEDED: frozenset(),
    FreightQuoteStatus.ACCEPTED: frozenset(),
}


def can_transition_quote(
    *,
    current: FreightQuoteStatus,
    target: FreightQuoteStatus,
) -> bool:
    return target in ALLOWED_QUOTE_STATUS_TRANSITIONS.get(current, frozenset())


REQUEST_STATUSES_ALLOWING_QUOTE_CREATION = frozenset(
    {
        "SUBMITTED",
        "UNDER_REVIEW",
        "QUOTING",
        "READY_TO_PUBLISH",
    }
)
