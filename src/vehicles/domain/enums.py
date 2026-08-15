from enum import StrEnum


class VehicleStatus(StrEnum):
    # Legacy value kept for migration compatibility.
    PENDING = "PENDING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    # Legacy value kept for historical records.
    IN_MAINTENANCE = "IN_MAINTENANCE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"
    SUSPENDED = "SUSPENDED"


class VehicleType(StrEnum):
    # Legacy values kept for compatibility.
    MOTORCYCLE = "MOTORCYCLE"
    CAR = "CAR"
    UTILITY = "UTILITY"
    PICKUP = "PICKUP"
    SEMI_TRUCK = "SEMI_TRUCK"
    TRAILER = "TRAILER"
    MOTO = "MOTO"
    CARRO = "CARRO"
    UTILITARIO = "UTILITARIO"
    VAN = "VAN"
    VUC = "VUC"
    TOCO = "TOCO"
    TRUCK = "TRUCK"
    CAVALO_MECANICO = "CAVALO_MECANICO"
    CARRETA = "CARRETA"
    BITREM = "BITREM"
    RODOTREM = "RODOTREM"


class VehicleOwnershipType(StrEnum):
    OWNED = "OWNED"
    AGGREGATED = "AGGREGATED"
    THIRD_PARTY = "THIRD_PARTY"
    # Legacy values kept for compatibility.
    AUTONOMOUS = "AUTONOMOUS"
    PARTNER = "PARTNER"
    SUBCONTRACTED = "SUBCONTRACTED"


class VehicleBodyType(StrEnum):
    BAU = "BAU"
    BAU_REFRIGERADO = "BAU_REFRIGERADO"
    SIDER = "SIDER"
    GRADE_BAIXA = "GRADE_BAIXA"
    GRANELEIRO = "GRANELEIRO"
    CACAMBA = "CACAMBA"
    PLATAFORMA = "PLATAFORMA"
    TANQUE = "TANQUE"
    CEGONHA = "CEGONHA"


class VehicleCargoProfile(StrEnum):
    DRY_CARGO = "DRY_CARGO"
    REFRIGERATED_CARGO = "REFRIGERATED_CARGO"
    BOTH = "BOTH"


class VehicleOperationalStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    MAINTENANCE = "MAINTENANCE"
    UNAVAILABLE = "UNAVAILABLE"


class RefrigerationControlType(StrEnum):
    MANUAL = "MANUAL"
    DIGITAL = "DIGITAL"
    AUTOMATED = "AUTOMATED"


class VehicleDocumentType(StrEnum):
    CRLV = "CRLV"
    LICENCIAMENTO = "LICENCIAMENTO"
    SEGURO = "SEGURO"
    RNTRC = "RNTRC"
    CERTIFICADO = "CERTIFICADO"
    REFRIGERACAO = "REFRIGERACAO"
    CALIBRACAO = "CALIBRACAO"
    OUTRO = "OUTRO"


from src.compliance.domain.enums import DocumentStatus as VehicleDocumentStatus  # noqa: E402, F401
