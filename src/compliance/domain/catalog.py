from dataclasses import dataclass

from src.carriers.domain.enums import CarrierDocumentType
from src.compliance.domain.enums import EntityType
from src.drivers.domain.enums import DriverDocumentType
from src.vehicles.domain.enums import VehicleDocumentType


@dataclass(frozen=True)
class DocumentTypeDefinition:
    code: str
    label: str
    entity_type: EntityType
    has_validity: bool = True
    required: bool = False
    allows_multiple_versions: bool = True
    requires_approval: bool = True
    blocks_operation_when_invalid: bool = False


DRIVER_DOCUMENT_DEFINITIONS: dict[str, DocumentTypeDefinition] = {
    DriverDocumentType.DRIVER_LICENSE.value: DocumentTypeDefinition(
        code=DriverDocumentType.DRIVER_LICENSE.value,
        label="CNH",
        entity_type=EntityType.DRIVER,
        required=True,
        blocks_operation_when_invalid=True,
    ),
    DriverDocumentType.PERSONAL_DOCUMENT.value: DocumentTypeDefinition(
        code=DriverDocumentType.PERSONAL_DOCUMENT.value,
        label="Identificação",
        entity_type=EntityType.DRIVER,
    ),
    DriverDocumentType.ADDRESS_PROOF.value: DocumentTypeDefinition(
        code=DriverDocumentType.ADDRESS_PROOF.value,
        label="Comprovante de endereço",
        entity_type=EntityType.DRIVER,
        has_validity=False,
    ),
    DriverDocumentType.CERTIFICATION.value: DocumentTypeDefinition(
        code=DriverDocumentType.CERTIFICATION.value,
        label="Certificação",
        entity_type=EntityType.DRIVER,
    ),
    DriverDocumentType.COURSE.value: DocumentTypeDefinition(
        code=DriverDocumentType.COURSE.value,
        label="Curso",
        entity_type=EntityType.DRIVER,
    ),
    DriverDocumentType.OPERATIONAL_EXAM.value: DocumentTypeDefinition(
        code=DriverDocumentType.OPERATIONAL_EXAM.value,
        label="Exame operacional",
        entity_type=EntityType.DRIVER,
    ),
    DriverDocumentType.OTHER.value: DocumentTypeDefinition(
        code=DriverDocumentType.OTHER.value,
        label="Outro",
        entity_type=EntityType.DRIVER,
        has_validity=False,
        requires_approval=False,
    ),
}

VEHICLE_DOCUMENT_DEFINITIONS: dict[str, DocumentTypeDefinition] = {
    VehicleDocumentType.CRLV.value: DocumentTypeDefinition(
        code=VehicleDocumentType.CRLV.value,
        label="CRLV",
        entity_type=EntityType.VEHICLE,
        required=True,
        blocks_operation_when_invalid=True,
    ),
    VehicleDocumentType.LICENCIAMENTO.value: DocumentTypeDefinition(
        code=VehicleDocumentType.LICENCIAMENTO.value,
        label="Licenciamento",
        entity_type=EntityType.VEHICLE,
    ),
    VehicleDocumentType.SEGURO.value: DocumentTypeDefinition(
        code=VehicleDocumentType.SEGURO.value,
        label="Seguro",
        entity_type=EntityType.VEHICLE,
    ),
    VehicleDocumentType.RNTRC.value: DocumentTypeDefinition(
        code=VehicleDocumentType.RNTRC.value,
        label="RNTRC",
        entity_type=EntityType.VEHICLE,
    ),
    VehicleDocumentType.CERTIFICADO.value: DocumentTypeDefinition(
        code=VehicleDocumentType.CERTIFICADO.value,
        label="Certificado",
        entity_type=EntityType.VEHICLE,
    ),
    VehicleDocumentType.REFRIGERACAO.value: DocumentTypeDefinition(
        code=VehicleDocumentType.REFRIGERACAO.value,
        label="Certificação frigorífica",
        entity_type=EntityType.VEHICLE,
    ),
    VehicleDocumentType.CALIBRACAO.value: DocumentTypeDefinition(
        code=VehicleDocumentType.CALIBRACAO.value,
        label="Calibração",
        entity_type=EntityType.VEHICLE,
    ),
    VehicleDocumentType.OUTRO.value: DocumentTypeDefinition(
        code=VehicleDocumentType.OUTRO.value,
        label="Outro",
        entity_type=EntityType.VEHICLE,
        has_validity=False,
        requires_approval=False,
    ),
}

CARRIER_DOCUMENT_DEFINITIONS: dict[str, DocumentTypeDefinition] = {
    CarrierDocumentType.CNPJ_CARD.value: DocumentTypeDefinition(
        code=CarrierDocumentType.CNPJ_CARD.value,
        label="Cartão CNPJ",
        entity_type=EntityType.CARRIER,
        has_validity=False,
    ),
    CarrierDocumentType.RNTRC_ANTT.value: DocumentTypeDefinition(
        code=CarrierDocumentType.RNTRC_ANTT.value,
        label="RNTRC / ANTT",
        entity_type=EntityType.CARRIER,
    ),
    CarrierDocumentType.CONTRACT.value: DocumentTypeDefinition(
        code=CarrierDocumentType.CONTRACT.value,
        label="Contrato",
        entity_type=EntityType.CARRIER,
        has_validity=False,
    ),
    CarrierDocumentType.INSURANCE_POLICY.value: DocumentTypeDefinition(
        code=CarrierDocumentType.INSURANCE_POLICY.value,
        label="Apólice",
        entity_type=EntityType.CARRIER,
    ),
    CarrierDocumentType.CORPORATE_DOCUMENT.value: DocumentTypeDefinition(
        code=CarrierDocumentType.CORPORATE_DOCUMENT.value,
        label="Documento societário",
        entity_type=EntityType.CARRIER,
        has_validity=False,
    ),
    CarrierDocumentType.CERTIFICATE.value: DocumentTypeDefinition(
        code=CarrierDocumentType.CERTIFICATE.value,
        label="Certificado",
        entity_type=EntityType.CARRIER,
    ),
    CarrierDocumentType.OTHER.value: DocumentTypeDefinition(
        code=CarrierDocumentType.OTHER.value,
        label="Outro",
        entity_type=EntityType.CARRIER,
        has_validity=False,
        requires_approval=False,
    ),
}

DOCUMENT_DEFINITIONS_BY_ENTITY: dict[EntityType, dict[str, DocumentTypeDefinition]] = {
    EntityType.DRIVER: DRIVER_DOCUMENT_DEFINITIONS,
    EntityType.VEHICLE: VEHICLE_DOCUMENT_DEFINITIONS,
    EntityType.CARRIER: CARRIER_DOCUMENT_DEFINITIONS,
}


def document_type_definition(
    entity_type: EntityType, document_type: str
) -> DocumentTypeDefinition | None:
    return DOCUMENT_DEFINITIONS_BY_ENTITY.get(entity_type, {}).get(document_type)


def required_document_types(entity_type: EntityType) -> tuple[str, ...]:
    definitions = DOCUMENT_DEFINITIONS_BY_ENTITY.get(entity_type, {})
    return tuple(code for code, definition in definitions.items() if definition.required)
