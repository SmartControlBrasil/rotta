from src.drivers.domain.route_intent_enums import DriverRouteIntentStatus

ALLOWED_ROUTE_INTENT_TRANSITIONS: dict[
    DriverRouteIntentStatus, frozenset[DriverRouteIntentStatus]
] = {
    DriverRouteIntentStatus.DRAFT: frozenset(
        {
            DriverRouteIntentStatus.ACTIVE,
            DriverRouteIntentStatus.CANCELLED,
        }
    ),
    DriverRouteIntentStatus.ACTIVE: frozenset(
        {
            DriverRouteIntentStatus.EXPIRED,
            DriverRouteIntentStatus.CANCELLED,
            DriverRouteIntentStatus.COMPLETED,
        }
    ),
    DriverRouteIntentStatus.EXPIRED: frozenset(),
    DriverRouteIntentStatus.CANCELLED: frozenset(),
    DriverRouteIntentStatus.COMPLETED: frozenset(),
}


def can_transition_route_intent(
    *,
    current: DriverRouteIntentStatus,
    target: DriverRouteIntentStatus,
) -> bool:
    return target in ALLOWED_ROUTE_INTENT_TRANSITIONS.get(current, frozenset())
