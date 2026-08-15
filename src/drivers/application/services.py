from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.carriers.infrastructure.django.models import CarrierDriverLink, CarrierProfile
from src.compliance.application.services import (
    _document_audit_payload as _compliance_document_audit_payload,
)
from src.compliance.application.services import approve_document, upload_document
from src.compliance.application.upload import ValidatedUpload
from src.compliance.domain.enums import EntityType
from src.drivers.domain.enums import (
    DriverApprovalStatus,
    DriverAvailabilityStatus,
    DriverDocumentType,
    DriverEngagementType,
    DriverStatus,
)
from src.drivers.infrastructure.django.models import Driver, DriverDocument
from src.organizations.infrastructure.django.models import Organization
from src.shared.application.storage import DocumentStoragePort
from src.vehicles.infrastructure.django.models import DriverVehicleAssignment, Vehicle


@dataclass(frozen=True)
class DriverData:
    organization: Organization
    full_name: str
    user: Any | None = None
    birth_date: date | None = None
    email: str = ""
    phone: str = ""
    mobile_phone: str = ""
    document: str = ""
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    country: str = "BR"
    driver_license_number: str = ""
    driver_license_category: str = ""
    driver_license_issue_state: str = ""
    driver_license_expiration: date | None = None
    engagement_type: DriverEngagementType = DriverEngagementType.OWNED
    status: DriverStatus = DriverStatus.PENDING
    availability_status: DriverAvailabilityStatus = DriverAvailabilityStatus.OFFLINE


@transaction.atomic
def register_driver(*, data: DriverData, actor=None) -> Driver:
    driver = Driver(
        organization=data.organization,
        user=data.user,
        full_name=data.full_name,
        birth_date=data.birth_date,
        email=data.email,
        phone=data.phone,
        mobile_phone=data.mobile_phone,
        document=data.document,
        postal_code=data.postal_code,
        street=data.street,
        number=data.number,
        complement=data.complement,
        district=data.district,
        city=data.city,
        state=data.state,
        country=data.country,
        driver_license_number=data.driver_license_number,
        driver_license_category=data.driver_license_category,
        driver_license_issue_state=data.driver_license_issue_state,
        driver_license_expiration=data.driver_license_expiration,
        engagement_type=data.engagement_type,
        status=data.status,
        availability_status=data.availability_status,
    )
    driver.full_clean()
    driver.save()
    record_audit_event(
        action="driver_created",
        actor=actor,
        organization=driver.organization,
        target=driver,
        after=_driver_audit_payload(driver),
    )
    return driver


@transaction.atomic
def update_driver(driver: Driver, *, actor=None, **changes) -> Driver:
    before = _driver_audit_payload(driver)
    allowed_fields = {
        "full_name",
        "birth_date",
        "email",
        "phone",
        "mobile_phone",
        "document",
        "postal_code",
        "street",
        "number",
        "complement",
        "district",
        "city",
        "state",
        "country",
        "driver_license_number",
        "driver_license_category",
        "driver_license_issue_state",
        "driver_license_expiration",
        "engagement_type",
        "status",
        "availability_status",
    }
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValidationError({field: "Campo não pode ser atualizado por este caso de uso."})
        setattr(driver, field, value)
    driver.full_clean()
    driver.save()
    record_audit_event(
        action="driver_updated",
        actor=actor,
        organization=driver.organization,
        target=driver,
        before=before,
        after=_driver_audit_payload(driver),
    )
    return driver


@transaction.atomic
def start_driver_review(driver: Driver, *, actor=None) -> Driver:
    before = _driver_audit_payload(driver)
    driver.approval_status = DriverApprovalStatus.UNDER_REVIEW
    driver.status = DriverStatus.UNDER_REVIEW
    driver.full_clean()
    driver.save(update_fields=["approval_status", "status", "updated_at"])
    record_audit_event(
        action="driver_under_review",
        actor=actor,
        organization=driver.organization,
        target=driver,
        before=before,
        after=_driver_audit_payload(driver),
    )
    return driver


@transaction.atomic
def approve_driver(driver: Driver, *, actor) -> Driver:
    if driver.has_expired_driver_license:
        raise ValidationError({"driver_license_expiration": "CNH vencida não permite aprovação."})
    before = _driver_audit_payload(driver)
    driver.approval_status = DriverApprovalStatus.APPROVED
    driver.status = DriverStatus.APPROVED
    driver.approved_at = timezone.now()
    driver.approved_by = actor
    driver.full_clean()
    driver.save(
        update_fields=["approval_status", "status", "approved_at", "approved_by", "updated_at"]
    )
    record_audit_event(
        action="driver_approved",
        actor=actor,
        organization=driver.organization,
        target=driver,
        before=before,
        after=_driver_audit_payload(driver),
    )
    return driver


@transaction.atomic
def suspend_driver(driver: Driver, *, actor=None, reason: str = "") -> Driver:
    before = _driver_audit_payload(driver)
    driver.approval_status = DriverApprovalStatus.SUSPENDED
    driver.status = DriverStatus.SUSPENDED
    driver.availability_status = DriverAvailabilityStatus.UNAVAILABLE
    driver.full_clean()
    driver.save(update_fields=["approval_status", "status", "availability_status", "updated_at"])
    record_audit_event(
        action="driver_suspended",
        actor=actor,
        organization=driver.organization,
        target=driver,
        before=before,
        after=_driver_audit_payload(driver),
        metadata={"reason": reason},
    )
    return driver


@transaction.atomic
def change_driver_status(
    driver: Driver, *, status: DriverStatus, actor=None, reason: str = ""
) -> Driver:
    before = _driver_audit_payload(driver)
    driver.status = status
    if status in {DriverStatus.BLOCKED, DriverStatus.SUSPENDED, DriverStatus.INACTIVE}:
        driver.availability_status = DriverAvailabilityStatus.UNAVAILABLE
    if (
        status == DriverStatus.ACTIVE
        and driver.availability_status == DriverAvailabilityStatus.UNAVAILABLE
    ):
        driver.availability_status = DriverAvailabilityStatus.AVAILABLE
    driver.full_clean()
    driver.save(update_fields=["status", "availability_status", "updated_at"])
    record_audit_event(
        action="driver_status_changed",
        actor=actor,
        organization=driver.organization,
        target=driver,
        before=before,
        after=_driver_audit_payload(driver),
        metadata={"status": status.value, "reason": reason},
    )
    return driver


@transaction.atomic
def assign_driver_to_vehicle_profile(
    *, driver: Driver, vehicle: Vehicle, valid_from: date, actor=None, primary: bool = False
) -> DriverVehicleAssignment:
    assignment = DriverVehicleAssignment(
        driver=driver,
        vehicle=vehicle,
        valid_from=valid_from,
        primary=primary,
        active=True,
    )
    assignment.full_clean()
    assignment.save()
    record_audit_event(
        action="driver_vehicle_assigned",
        actor=actor,
        organization=driver.organization,
        target=assignment,
        after={
            "id": str(assignment.id),
            "driver_id": str(driver.id),
            "vehicle_id": str(vehicle.id),
            "active": assignment.active,
            "primary": assignment.primary,
        },
    )
    return assignment


@transaction.atomic
def unassign_driver_vehicle_profile(
    assignment: DriverVehicleAssignment, *, valid_until: date, actor=None
) -> DriverVehicleAssignment:
    before = {
        "id": str(assignment.id),
        "active": assignment.active,
        "primary": assignment.primary,
        "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else "",
    }
    if valid_until < assignment.valid_from:
        raise ValidationError({"valid_until": "Fim da vigência não pode ser anterior ao início."})
    assignment.active = False
    assignment.primary = False
    assignment.valid_until = valid_until
    assignment.full_clean()
    assignment.save(update_fields=["active", "primary", "valid_until", "updated_at"])
    record_audit_event(
        action="driver_vehicle_unassigned",
        actor=actor,
        organization=assignment.driver.organization,
        target=assignment,
        before=before,
        after={
            "id": str(assignment.id),
            "active": assignment.active,
            "primary": assignment.primary,
            "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else "",
        },
    )
    return assignment


@transaction.atomic
def link_driver_to_carrier(
    *, driver: Driver, carrier: CarrierProfile, actor=None
) -> CarrierDriverLink:
    link, created = CarrierDriverLink.objects.get_or_create(
        carrier=carrier,
        driver=driver,
        defaults={"active": True},
    )
    if not created and not link.active:
        link.active = True
    link.full_clean()
    link.save()
    record_audit_event(
        action="driver_carrier_linked",
        actor=actor,
        organization=driver.organization,
        target=link,
        after={
            "id": str(link.id),
            "driver_id": str(driver.id),
            "carrier_id": str(carrier.id),
            "active": link.active,
        },
    )
    return link


@transaction.atomic
def unlink_driver_from_carrier(link: CarrierDriverLink, *, actor=None) -> CarrierDriverLink:
    before = {
        "id": str(link.id),
        "driver_id": str(link.driver_id),
        "carrier_id": str(link.carrier_id),
        "active": link.active,
    }
    link.active = False
    link.full_clean()
    link.save(update_fields=["active", "updated_at"])
    record_audit_event(
        action="driver_carrier_unlinked",
        actor=actor,
        organization=link.driver.organization,
        target=link,
        before=before,
        after={
            "id": str(link.id),
            "driver_id": str(link.driver_id),
            "carrier_id": str(link.carrier_id),
            "active": link.active,
        },
    )
    return link


@transaction.atomic
def add_driver_document(
    *,
    driver: Driver,
    document_type: DriverDocumentType,
    storage: DocumentStoragePort,
    content,
    filename: str,
    actor=None,
    expiration_date: date | None = None,
    issue_date: date | None = None,
) -> DriverDocument:
    validated = ValidatedUpload(
        content=content,
        safe_filename=filename,
        original_filename=filename,
        content_type="application/octet-stream",
        content_hash="",
        size_bytes=len(content.getvalue()) if hasattr(content, "getvalue") else 0,
    )
    document = upload_document(
        entity_type=EntityType.DRIVER,
        entity_id=str(driver.id),
        document_type=document_type.value,
        validated_upload=validated,
        storage=storage,
        actor=actor,
        issue_date=issue_date,
        expiration_date=expiration_date,
    )
    return document


@transaction.atomic
def verify_driver_document(document: DriverDocument, *, actor) -> DriverDocument:
    return approve_document(document=document, entity_type=EntityType.DRIVER, actor=actor)


def _driver_audit_payload(driver: Driver) -> dict[str, Any]:
    return {
        "id": str(driver.id),
        "organization_id": str(driver.organization_id),
        "user_id": str(driver.user_id) if driver.user_id else "",
        "full_name": driver.full_name,
        "birth_date": driver.birth_date.isoformat() if driver.birth_date else "",
        "email": "[REDACTED]" if driver.email else "",
        "phone": driver.phone,
        "mobile_phone": "[REDACTED]" if driver.mobile_phone else "",
        "document": "[REDACTED]" if driver.document else "",
        "postal_code": driver.postal_code,
        "street": driver.street,
        "number": driver.number,
        "complement": driver.complement,
        "district": driver.district,
        "city": driver.city,
        "state": driver.state,
        "country": driver.country,
        "driver_license_number": "[REDACTED]" if driver.driver_license_number else "",
        "driver_license_category": driver.driver_license_category,
        "driver_license_issue_state": driver.driver_license_issue_state,
        "driver_license_expiration": driver.driver_license_expiration.isoformat()
        if driver.driver_license_expiration
        else "",
        "engagement_type": driver.engagement_type,
        "status": driver.status,
        "approval_status": driver.approval_status,
        "availability_status": driver.availability_status,
    }


def _document_audit_payload(document: DriverDocument) -> dict[str, Any]:
    return _compliance_document_audit_payload(document, entity_type=EntityType.DRIVER)
