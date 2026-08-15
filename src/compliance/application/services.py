from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.carriers.infrastructure.django.models import CarrierDocument, CarrierProfile
from src.compliance.application.upload import ValidatedUpload
from src.compliance.domain.enums import ACTIVE_DOCUMENT_STATUSES, DocumentStatus, EntityType
from src.drivers.infrastructure.django.models import Driver, DriverDocument
from src.shared.application.storage import DocumentStoragePort
from src.vehicles.infrastructure.django.models import Vehicle, VehicleDocument


class DocumentModel(Protocol):
    id: Any
    document_type: str
    storage_key: str
    status: str
    expiration_date: date | None
    issue_date: date | None
    original_filename: str
    content_hash: str
    notes: str
    reviewed_at: Any
    reviewed_by: Any
    rejection_reason: str
    replaced_by_id: Any

    def save(self, *args, **kwargs): ...


@dataclass(frozen=True)
class UnifiedDocument:
    id: str
    entity_type: EntityType
    entity_id: str
    entity_label: str
    organization_id: str
    document_type: str
    status: str
    issue_date: date | None
    expiration_date: date | None
    reviewed_by_id: str
    reviewed_by_label: str
    original_filename: str
    created_at: Any
    instance: DocumentModel

    @property
    def pk(self) -> str:
        return self.id


def _document_audit_payload(document: DocumentModel, *, entity_type: EntityType) -> dict[str, Any]:
    entity_id = ""
    if entity_type == EntityType.DRIVER:
        entity_id = str(document.driver_id)  # type: ignore[attr-defined]
    elif entity_type == EntityType.VEHICLE:
        entity_id = str(document.vehicle_id)  # type: ignore[attr-defined]
    elif entity_type == EntityType.CARRIER:
        entity_id = str(document.carrier_id)  # type: ignore[attr-defined]

    return {
        "id": str(document.id),
        "entity_type": entity_type.value,
        "entity_id": entity_id,
        "document_type": document.document_type,
        "storage_key": "[REDACTED]" if document.storage_key else "",
        "status": document.status,
        "issue_date": document.issue_date.isoformat() if document.issue_date else "",
        "expiration_date": document.expiration_date.isoformat() if document.expiration_date else "",
        "content_hash": document.content_hash[:12] + "..." if document.content_hash else "",
        "reviewed_by_id": str(document.reviewed_by_id) if document.reviewed_by_id else "",
    }


def _storage_prefix(entity_type: EntityType, entity_id: str) -> str:
    mapping = {
        EntityType.DRIVER: "drivers",
        EntityType.VEHICLE: "vehicles",
        EntityType.CARRIER: "carriers",
    }
    return f"{mapping[entity_type]}/{entity_id}"


def _get_entity(entity_type: EntityType, entity_id: str):
    if entity_type == EntityType.DRIVER:
        return Driver.objects.get(pk=entity_id)
    if entity_type == EntityType.VEHICLE:
        return Vehicle.objects.get(pk=entity_id)
    if entity_type == EntityType.CARRIER:
        return CarrierProfile.objects.get(pk=entity_id)
    raise ValidationError({"entity_type": "Tipo de entidade inválido."})


def _organization_for_entity(entity_type: EntityType, entity):
    if entity_type == EntityType.CARRIER:
        return entity.tenant
    return entity.organization


def _document_model(entity_type: EntityType):
    mapping = {
        EntityType.DRIVER: DriverDocument,
        EntityType.VEHICLE: VehicleDocument,
        EntityType.CARRIER: CarrierDocument,
    }
    return mapping[entity_type]


def _entity_fk_field(entity_type: EntityType) -> str:
    mapping = {
        EntityType.DRIVER: "driver",
        EntityType.VEHICLE: "vehicle",
        EntityType.CARRIER: "carrier",
    }
    return mapping[entity_type]


@transaction.atomic
def upload_document(
    *,
    entity_type: EntityType,
    entity_id: str,
    document_type: str,
    validated_upload: ValidatedUpload,
    storage: DocumentStoragePort,
    actor=None,
    issue_date: date | None = None,
    expiration_date: date | None = None,
    notes: str = "",
    replace_document_id: str | None = None,
) -> DocumentModel:
    entity = _get_entity(entity_type, entity_id)
    organization = _organization_for_entity(entity_type, entity)
    model = _document_model(entity_type)
    fk_field = _entity_fk_field(entity_type)

    replaced_document = None
    if replace_document_id:
        replaced_document = model.objects.select_for_update().get(
            pk=replace_document_id, **{f"{fk_field}_id": entity_id}
        )
        if replaced_document.status == DocumentStatus.REPLACED.value:
            raise ValidationError({"replace_document_id": "Documento já foi substituído."})

    storage_key = storage.save(
        f"{_storage_prefix(entity_type, entity_id)}/{validated_upload.safe_filename}",
        validated_upload.content,
    )
    document = model(
        **{
            fk_field: entity,
            "document_type": document_type,
            "storage_key": storage_key,
            "issue_date": issue_date,
            "expiration_date": expiration_date,
            "original_filename": validated_upload.original_filename,
            "content_hash": validated_upload.content_hash,
            "notes": notes,
            "status": DocumentStatus.PENDING.value,
        }
    )
    document.full_clean()
    document.save()

    if replaced_document is not None:
        replaced_document.status = DocumentStatus.REPLACED.value
        replaced_document.replaced_by = document
        replaced_document.full_clean()
        replaced_document.save(update_fields=["status", "replaced_by", "updated_at"])
        record_audit_event(
            action="document_replaced",
            actor=actor,
            organization=organization,
            target=replaced_document,
            before={"status": DocumentStatus.APPROVED.value},
            after=_document_audit_payload(replaced_document, entity_type=entity_type),
            metadata={"replacement_id": str(document.id)},
        )

    record_audit_event(
        action="document_uploaded",
        actor=actor,
        organization=organization,
        target=document,
        after=_document_audit_payload(document, entity_type=entity_type),
    )
    return document


@transaction.atomic
def start_document_review(
    *, document: DocumentModel, entity_type: EntityType, actor=None
) -> DocumentModel:
    if document.status not in {DocumentStatus.PENDING.value, DocumentStatus.REJECTED.value}:
        raise ValidationError(
            {"status": "Somente documentos pendentes ou rejeitados entram em análise."}
        )
    before = _document_audit_payload(document, entity_type=entity_type)
    document.status = DocumentStatus.UNDER_REVIEW.value
    document.rejection_reason = ""
    document.full_clean()
    document.save(update_fields=["status", "rejection_reason", "updated_at"])
    organization = _organization_for_entity(
        entity_type, _entity_from_document(document, entity_type)
    )
    record_audit_event(
        action="document_review_started",
        actor=actor,
        organization=organization,
        target=document,
        before=before,
        after=_document_audit_payload(document, entity_type=entity_type),
    )
    return document


@transaction.atomic
def approve_document(*, document: DocumentModel, entity_type: EntityType, actor) -> DocumentModel:
    if document.status not in {
        DocumentStatus.PENDING.value,
        DocumentStatus.UNDER_REVIEW.value,
    }:
        raise ValidationError({"status": "Documento não está elegível para aprovação."})
    if document.expiration_date and document.expiration_date < timezone.localdate():
        raise ValidationError({"expiration_date": "Documento vencido não pode ser aprovado."})
    before = _document_audit_payload(document, entity_type=entity_type)
    document.status = DocumentStatus.APPROVED.value
    document.reviewed_at = timezone.now()
    document.reviewed_by = actor
    document.rejection_reason = ""
    document.full_clean()
    document.save(
        update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason", "updated_at"]
    )
    organization = _organization_for_entity(
        entity_type, _entity_from_document(document, entity_type)
    )
    record_audit_event(
        action="document_approved",
        actor=actor,
        organization=organization,
        target=document,
        before=before,
        after=_document_audit_payload(document, entity_type=entity_type),
    )
    return document


@transaction.atomic
def reject_document(
    *,
    document: DocumentModel,
    entity_type: EntityType,
    actor,
    rejection_reason: str,
) -> DocumentModel:
    if not rejection_reason.strip():
        raise ValidationError({"rejection_reason": "Motivo da rejeição é obrigatório."})
    if document.status not in {
        DocumentStatus.PENDING.value,
        DocumentStatus.UNDER_REVIEW.value,
        DocumentStatus.APPROVED.value,
    }:
        raise ValidationError({"status": "Documento não está elegível para rejeição."})
    before = _document_audit_payload(document, entity_type=entity_type)
    document.status = DocumentStatus.REJECTED.value
    document.reviewed_at = timezone.now()
    document.reviewed_by = actor
    document.rejection_reason = rejection_reason.strip()
    document.full_clean()
    document.save(
        update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason", "updated_at"]
    )
    organization = _organization_for_entity(
        entity_type, _entity_from_document(document, entity_type)
    )
    record_audit_event(
        action="document_rejected",
        actor=actor,
        organization=organization,
        target=document,
        before=before,
        after=_document_audit_payload(document, entity_type=entity_type),
        metadata={"rejection_reason": rejection_reason.strip()},
    )
    return document


def record_document_download(*, document: DocumentModel, entity_type: EntityType, actor) -> None:
    organization = _organization_for_entity(
        entity_type, _entity_from_document(document, entity_type)
    )
    record_audit_event(
        action="document_downloaded",
        actor=actor,
        organization=organization,
        target=document,
        after=_document_audit_payload(document, entity_type=entity_type),
    )


def _entity_from_document(document: DocumentModel, entity_type: EntityType):
    if entity_type == EntityType.DRIVER:
        return document.driver  # type: ignore[attr-defined]
    if entity_type == EntityType.VEHICLE:
        return document.vehicle  # type: ignore[attr-defined]
    return document.carrier  # type: ignore[attr-defined]


def resolve_document(*, document_id: str) -> tuple[DocumentModel, EntityType] | None:
    for entity_type, model in (
        (EntityType.DRIVER, DriverDocument),
        (EntityType.VEHICLE, VehicleDocument),
        (EntityType.CARRIER, CarrierDocument),
    ):
        document = model.objects.filter(pk=document_id).first()
        if document is not None:
            return document, entity_type
    return None


def unified_document_from_instance(
    document: DocumentModel, entity_type: EntityType
) -> UnifiedDocument:
    entity = _entity_from_document(document, entity_type)
    if entity_type == EntityType.DRIVER:
        entity_label = entity.full_name
        organization_id = str(entity.organization_id)
    elif entity_type == EntityType.VEHICLE:
        entity_label = entity.plate
        organization_id = str(entity.organization_id)
    else:
        entity_label = entity.trade_name or entity.organization.name
        organization_id = str(entity.tenant_id)

    reviewer_label = ""
    if document.reviewed_by_id:
        reviewer_label = getattr(document.reviewed_by, "username", "") or str(
            document.reviewed_by_id
        )

    return UnifiedDocument(
        id=str(document.id),
        entity_type=entity_type,
        entity_id=str(entity.id),
        entity_label=entity_label,
        organization_id=organization_id,
        document_type=document.document_type,
        status=document.status,
        issue_date=document.issue_date,
        expiration_date=document.expiration_date,
        reviewed_by_id=str(document.reviewed_by_id) if document.reviewed_by_id else "",
        reviewed_by_label=reviewer_label,
        original_filename=document.original_filename,
        created_at=document.created_at,
        instance=document,
    )


def active_status_values() -> tuple[str, ...]:
    return tuple(status.value for status in ACTIVE_DOCUMENT_STATUSES)
