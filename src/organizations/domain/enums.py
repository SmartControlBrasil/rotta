from enum import StrEnum


class OrganizationType(StrEnum):
    TRANSPORT_COMPANY = "TRANSPORT_COMPANY"
    CUSTOMER = "CUSTOMER"
    PARTNER = "PARTNER"
    SUPPLIER = "SUPPLIER"
    FLEET_OWNER = "FLEET_OWNER"
    OTHER = "OTHER"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    SUSPENDED = "SUSPENDED"
    LEFT = "LEFT"
