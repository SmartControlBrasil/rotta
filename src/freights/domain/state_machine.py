from src.freights.domain.enums import FreightRequestStatus

ALLOWED_STATUS_TRANSITIONS: dict[FreightRequestStatus, frozenset[FreightRequestStatus]] = {
    FreightRequestStatus.DRAFT: frozenset(
        {FreightRequestStatus.SUBMITTED, FreightRequestStatus.CANCELLED}
    ),
    FreightRequestStatus.SUBMITTED: frozenset(
        {FreightRequestStatus.UNDER_REVIEW, FreightRequestStatus.CANCELLED}
    ),
    FreightRequestStatus.UNDER_REVIEW: frozenset(
        {
            FreightRequestStatus.QUOTING,
            FreightRequestStatus.CANCELLED,
        }
    ),
    FreightRequestStatus.QUOTING: frozenset(
        {FreightRequestStatus.READY_TO_PUBLISH, FreightRequestStatus.CANCELLED}
    ),
    FreightRequestStatus.READY_TO_PUBLISH: frozenset(
        {FreightRequestStatus.CLOSED, FreightRequestStatus.CANCELLED}
    ),
    FreightRequestStatus.CANCELLED: frozenset(),
    FreightRequestStatus.CLOSED: frozenset(),
}


def can_transition(
    *,
    current: FreightRequestStatus,
    target: FreightRequestStatus,
) -> bool:
    return target in ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())
