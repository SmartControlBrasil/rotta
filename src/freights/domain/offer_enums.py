from enum import StrEnum


class FreightOfferStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class FreightOfferAudience(StrEnum):
    CARRIERS = "CARRIERS"
    DRIVERS = "DRIVERS"
    BOTH = "BOTH"
    PRIVATE = "PRIVATE"
