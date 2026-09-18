from enum import StrEnum


class FreightRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    QUOTING = "QUOTING"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class FreightStopType(StrEnum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class FreightCargoProfile(StrEnum):
    DRY_CARGO = "DRY_CARGO"
    REFRIGERATED_CARGO = "REFRIGERATED_CARGO"


class FreightCargoType(StrEnum):
    GENERAL_CARGO = "GENERAL_CARGO"
    FOOD = "FOOD"
    BEVERAGE = "BEVERAGE"
    PHARMACEUTICAL = "PHARMACEUTICAL"
    ELECTRONICS = "ELECTRONICS"
    MACHINERY = "MACHINERY"
    CONSTRUCTION_MATERIAL = "CONSTRUCTION_MATERIAL"
    OTHER = "OTHER"


class FreightRequestPriority(StrEnum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class OperationStatus(StrEnum):
    ASSIGNED = "ASSIGNED"
    DRIVER_EN_ROUTE_TO_PICKUP = "DRIVER_EN_ROUTE_TO_PICKUP"
    ARRIVED_AT_PICKUP = "ARRIVED_AT_PICKUP"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED_AT_DELIVERY = "ARRIVED_AT_DELIVERY"
    UNLOADING = "UNLOADING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OperationEventType(StrEnum):
    OPERATION_CREATED = "OPERATION_CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    INCIDENT_REPORTED = "INCIDENT_REPORTED"
    POD_CREATED = "POD_CREATED"
    CANCELLED = "CANCELLED"


class LoadType(StrEnum):
    FTL = "FTL"
    LTL = "LTL"


class OperationEventOrigin(StrEnum):
    BACKOFFICE = "BACKOFFICE"
    MOBILE_APP = "MOBILE_APP"
    API = "API"
    SYSTEM = "SYSTEM"


class TrackingSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ThermalReadingQuality(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    SUSPECT = "SUSPECT"
    STALE = "STALE"


class ThermalReadingValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    SUSPECT = "SUSPECT"
    STALE = "STALE"


class ThermalExcursionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class ThermalExcursionDirection(StrEnum):
    BELOW_MIN = "BELOW_MIN"
    ABOVE_MAX = "ABOVE_MAX"


class OperationSource(StrEnum):
    MARKETPLACE = "MARKETPLACE"
    CONTRACTED_ROUTE = "CONTRACTED_ROUTE"
    MANUAL = "MANUAL"
    API = "API"


class ContractedRouteStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ContractedRouteOccurrenceStatus(StrEnum):
    PLANNED = "PLANNED"
    MATERIALIZED = "MATERIALIZED"
    CANCELLED = "CANCELLED"


class RouteWeekday(StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"
