from enum import StrEnum


class CarrierStatus(StrEnum):
    PROSPECT = "PROSPECT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    INACTIVE = "INACTIVE"


class CarrierCargoProfile(StrEnum):
    DRY_CARGO = "DRY_CARGO"
    REFRIGERATED_CARGO = "REFRIGERATED_CARGO"
    BOTH = "BOTH"


class CarrierDocumentType(StrEnum):
    CNPJ_CARD = "CNPJ_CARD"
    RNTRC_ANTT = "RNTRC_ANTT"
    CONTRACT = "CONTRACT"
    INSURANCE_POLICY = "INSURANCE_POLICY"
    CORPORATE_DOCUMENT = "CORPORATE_DOCUMENT"
    CERTIFICATE = "CERTIFICATE"
    OTHER = "OTHER"


from src.compliance.domain.enums import DocumentStatus as CarrierDocumentStatus  # noqa: E402, F401


class CarrierVehicleLinkType(StrEnum):
    OWNED = "OWNED"
    AGGREGATED = "AGGREGATED"
    THIRD_PARTY = "THIRD_PARTY"
    SUBCONTRACTED = "SUBCONTRACTED"
