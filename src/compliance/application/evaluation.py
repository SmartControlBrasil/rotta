from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from src.compliance.application.expiration import document_validity_status, is_document_expired
from src.compliance.domain.catalog import document_type_definition, required_document_types
from src.compliance.domain.enums import (
    ACTIVE_DOCUMENT_STATUSES,
    ComplianceStatus,
    DocumentStatus,
    DocumentValidityStatus,
    EntityType,
)


@dataclass(frozen=True)
class EntityComplianceResult:
    status: ComplianceStatus
    required_types: tuple[str, ...]
    missing_types: tuple[str, ...]
    pending_types: tuple[str, ...]
    rejected_types: tuple[str, ...]
    expired_types: tuple[str, ...]
    expiring_types: tuple[str, ...]

    @property
    def is_operationally_compliant(self) -> bool:
        return self.status == ComplianceStatus.COMPLIANT


def _active_documents(documents, document_type: str):
    return [
        document
        for document in documents
        if document.document_type == document_type
        and document.status in {status.value for status in ACTIVE_DOCUMENT_STATUSES}
    ]


def evaluate_entity_compliance(
    *,
    entity_type: EntityType,
    documents,
    reference_date: date | None = None,
) -> EntityComplianceResult:
    today = reference_date or timezone.localdate()
    required = required_document_types(entity_type)
    missing: list[str] = []
    pending: list[str] = []
    rejected: list[str] = []
    expired: list[str] = []
    expiring: list[str] = []

    for document_type in required:
        active_docs = _active_documents(documents, document_type)
        if not active_docs:
            missing.append(document_type)
            continue

        approved_docs = [
            document for document in active_docs if document.status == DocumentStatus.APPROVED.value
        ]
        if not approved_docs:
            if any(document.status == DocumentStatus.REJECTED.value for document in active_docs):
                rejected.append(document_type)
            else:
                pending.append(document_type)
            continue

        approved_doc = approved_docs[0]
        definition = document_type_definition(entity_type, document_type)
        if definition and definition.has_validity:
            if is_document_expired(
                expiration_date=approved_doc.expiration_date, reference_date=today
            ):
                expired.append(document_type)
                continue
            validity = document_validity_status(
                expiration_date=approved_doc.expiration_date,
                reference_date=today,
            )
            if validity == DocumentValidityStatus.EXPIRING:
                expiring.append(document_type)

    if missing or rejected or expired:
        status = ComplianceStatus.NON_COMPLIANT
    elif pending:
        status = ComplianceStatus.PENDING
    elif expiring:
        status = ComplianceStatus.WARNING
    else:
        status = ComplianceStatus.COMPLIANT

    return EntityComplianceResult(
        status=status,
        required_types=required,
        missing_types=tuple(missing),
        pending_types=tuple(pending),
        rejected_types=tuple(rejected),
        expired_types=tuple(expired),
        expiring_types=tuple(expiring),
    )
