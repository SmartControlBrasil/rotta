from enum import StrEnum


class DriverRouteIntentType(StrEnum):
    RETURN_LOAD = "RETURN_LOAD"
    DESTINATION_PREFERENCE = "DESTINATION_PREFERENCE"


class DriverRouteIntentStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class DriverRouteIntentSource(StrEnum):
    BACKOFFICE = "BACKOFFICE"
    DRIVER_APP = "DRIVER_APP"
    SYSTEM = "SYSTEM"


class RouteIntentCargoPreference(StrEnum):
    DRY_CARGO = "DRY_CARGO"
    REFRIGERATED_CARGO = "REFRIGERATED_CARGO"
    BOTH = "BOTH"


class RouteIntentCompatibilityLevel(StrEnum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"
