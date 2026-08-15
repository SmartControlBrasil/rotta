from enum import StrEnum


class DriverStatus(StrEnum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    INACTIVE = "INACTIVE"


class DriverApprovalStatus(StrEnum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class DriverAvailabilityStatus(StrEnum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    PAUSED = "PAUSED"
    UNAVAILABLE = "UNAVAILABLE"


class DriverDocumentType(StrEnum):
    DRIVER_LICENSE = "DRIVER_LICENSE"
    ADDRESS_PROOF = "ADDRESS_PROOF"
    PERSONAL_DOCUMENT = "PERSONAL_DOCUMENT"
    CERTIFICATION = "CERTIFICATION"
    COURSE = "COURSE"
    OPERATIONAL_EXAM = "OPERATIONAL_EXAM"
    OTHER = "OTHER"


from src.compliance.domain.enums import DocumentStatus as DriverDocumentStatus  # noqa: E402, F401


class DriverEngagementType(StrEnum):
    OWNED = "OWNED"
    AGGREGATED = "AGGREGATED"
    CARRIER = "CARRIER"
    PARTNER = "PARTNER"


class DriverLicenseCategory(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    AB = "AB"
    AC = "AC"
    AD = "AD"
    AE = "AE"
