from enum import StrEnum


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REPLACED = "REPLACED"


ACTIVE_DOCUMENT_STATUSES = frozenset(
    {
        DocumentStatus.PENDING,
        DocumentStatus.UNDER_REVIEW,
        DocumentStatus.APPROVED,
    }
)


class EntityType(StrEnum):
    DRIVER = "DRIVER"
    VEHICLE = "VEHICLE"
    CARRIER = "CARRIER"


class ComplianceStatus(StrEnum):
    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    PENDING = "PENDING"
    NON_COMPLIANT = "NON_COMPLIANT"


class DocumentValidityStatus(StrEnum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    NO_EXPIRATION = "NO_EXPIRATION"
