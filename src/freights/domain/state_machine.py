from src.freights.domain.enums import FreightRequestStatus, OperationStatus

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

# Operation status transitions
ALLOWED_OPERATION_STATUS_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.ASSIGNED: frozenset({
        OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP: frozenset({
        OperationStatus.ARRIVED_AT_PICKUP,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.ARRIVED_AT_PICKUP: frozenset({
        OperationStatus.LOADING,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.LOADING: frozenset({
        OperationStatus.IN_TRANSIT,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.IN_TRANSIT: frozenset({
        OperationStatus.ARRIVED_AT_DELIVERY,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.ARRIVED_AT_DELIVERY: frozenset({
        OperationStatus.UNLOADING,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.UNLOADING: frozenset({
        OperationStatus.DELIVERED,
        OperationStatus.CANCELLED,
    }),
    OperationStatus.DELIVERED: frozenset(),
    OperationStatus.CANCELLED: frozenset(),
}

def can_operation_transition(*, current: OperationStatus, target: OperationStatus) -> bool:
    return target in ALLOWED_OPERATION_STATUS_TRANSITIONS.get(current, frozenset())
