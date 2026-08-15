from datetime import timedelta
from io import BytesIO, StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.infrastructure.django.models import CarrierDocument, CarrierProfile
from src.compliance.application.evaluation import evaluate_entity_compliance
from src.compliance.application.expiration import document_validity_status
from src.compliance.application.services import approve_document, reject_document, upload_document
from src.compliance.application.upload import validate_upload_file
from src.compliance.domain.enums import (
    ComplianceStatus,
    DocumentStatus,
    DocumentValidityStatus,
    EntityType,
)
from src.drivers.application.services import add_driver_document, verify_driver_document
from src.drivers.domain.enums import DriverDocumentType
from src.drivers.infrastructure.django.models import Driver
from src.identity.domain.enums import RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.infrastructure.django.storage import PrivateDocumentStorageAdapter
from src.vehicles.domain.enums import VehicleDocumentType
from src.vehicles.infrastructure.django.models import Vehicle, VehicleDocument


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Rotta Compliance Org",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization():
    return Organization.objects.create(
        name="Outra Org",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


def make_upload(content: bytes, filename: str):
    class Upload:
        def __init__(self):
            self.name = filename
            self.content_type = "application/pdf"
            self._content = content

        def read(self):
            return self._content

    return Upload()


@pytest.mark.django_db(transaction=True)
def test_document_validity_status_calculation():
    today = timezone.localdate()
    assert (
        document_validity_status(expiration_date=today + timedelta(days=60))
        == DocumentValidityStatus.VALID
    )
    assert (
        document_validity_status(expiration_date=today + timedelta(days=10))
        == DocumentValidityStatus.EXPIRING
    )
    assert (
        document_validity_status(expiration_date=today - timedelta(days=1))
        == DocumentValidityStatus.EXPIRED
    )
    assert document_validity_status(expiration_date=None) == DocumentValidityStatus.NO_EXPIRATION


@pytest.mark.django_db(transaction=True)
def test_driver_compliance_requires_approved_cnh(organization):
    driver = Driver.objects.create(organization=organization, full_name="Sem CNH")
    result = evaluate_entity_compliance(
        entity_type=EntityType.DRIVER, documents=driver.documents.all()
    )
    assert result.status == ComplianceStatus.NON_COMPLIANT
    assert "DRIVER_LICENSE" in result.missing_types


@pytest.mark.django_db(transaction=True)
def test_upload_document_private_storage_and_audit(
    django_user_model, organization, tmp_path, settings
):
    settings.PRIVATE_DOCUMENT_STORAGE_ROOT = tmp_path
    actor = django_user_model.objects.create_user(username="uploader", password="safe-pass-123")
    driver = Driver.objects.create(organization=organization, full_name="Upload Test")
    storage = PrivateDocumentStorageAdapter()
    validated = validate_upload_file(uploaded_file=make_upload(b"%PDF-1.4 test", "cnh.pdf"))

    document = upload_document(
        entity_type=EntityType.DRIVER,
        entity_id=str(driver.id),
        document_type=DriverDocumentType.DRIVER_LICENSE.value,
        validated_upload=validated,
        storage=storage,
        actor=actor,
        expiration_date=timezone.localdate() + timedelta(days=30),
    )

    assert storage.exists(document.storage_key)
    assert document.status == DocumentStatus.PENDING.value
    audit = AuditLog.objects.filter(action="document_uploaded", target_id=str(document.id)).exists()
    assert audit


@pytest.mark.django_db(transaction=True)
def test_approve_and_reject_document_flow(django_user_model, organization, tmp_path, settings):
    settings.PRIVATE_DOCUMENT_STORAGE_ROOT = tmp_path
    reviewer = django_user_model.objects.create_user(username="reviewer", password="safe-pass-123")
    driver = Driver.objects.create(organization=organization, full_name="Review Test")
    storage = PrivateDocumentStorageAdapter()
    validated = validate_upload_file(uploaded_file=make_upload(b"%PDF-1.4 test", "doc.pdf"))
    document = upload_document(
        entity_type=EntityType.DRIVER,
        entity_id=str(driver.id),
        document_type=DriverDocumentType.PERSONAL_DOCUMENT.value,
        validated_upload=validated,
        storage=storage,
        actor=reviewer,
    )

    approved = approve_document(document=document, entity_type=EntityType.DRIVER, actor=reviewer)
    assert approved.status == DocumentStatus.APPROVED.value
    assert AuditLog.objects.filter(action="document_approved", target_id=str(document.id)).exists()

    with pytest.raises(ValidationError):
        reject_document(
            document=approved,
            entity_type=EntityType.DRIVER,
            actor=reviewer,
            rejection_reason="",
        )

    rejected = reject_document(
        document=approved,
        entity_type=EntityType.DRIVER,
        actor=reviewer,
        rejection_reason="Documento ilegível",
    )
    assert rejected.status == DocumentStatus.REJECTED.value


@pytest.mark.django_db(transaction=True)
def test_document_download_requires_scope(
    client, django_user_model, organization, other_organization, rbac_ready, tmp_path, settings
):
    settings.PRIVATE_DOCUMENT_STORAGE_ROOT = tmp_path
    authorized = django_user_model.objects.create_user(
        username="docadmin", password="safe-pass-123"
    )
    outsider = django_user_model.objects.create_user(
        username="docoutsider", password="safe-pass-123"
    )
    grant(authorized, organization, RoleCode.COMPANY_ADMIN)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN)

    driver = Driver.objects.create(organization=organization, full_name="Protegido")
    storage = PrivateDocumentStorageAdapter()
    document = add_driver_document(
        driver=driver,
        document_type=DriverDocumentType.DRIVER_LICENSE,
        storage=storage,
        content=BytesIO(b"%PDF-1.4 private"),
        filename="safe.pdf",
        actor=authorized,
        expiration_date=timezone.localdate() + timedelta(days=10),
    )

    client.force_login(authorized)
    response = client.get(reverse("backoffice:document_download", kwargs={"pk": document.id}))
    assert response.status_code == 200
    assert AuditLog.objects.filter(
        action="document_downloaded", target_id=str(document.id)
    ).exists()

    client.force_login(outsider)
    assert (
        client.get(reverse("backoffice:document_download", kwargs={"pk": document.id})).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True)
def test_documents_list_and_compliance_dashboard_rbac(
    client, django_user_model, organization, rbac_ready
):
    admin = django_user_model.objects.create_user(username="comp-admin", password="safe-pass-123")
    viewer = django_user_model.objects.create_user(username="comp-viewer", password="safe-pass-123")
    grant(admin, organization, RoleCode.COMPANY_ADMIN)
    grant(viewer, organization, RoleCode.VIEWER)

    client.force_login(admin)
    assert client.get(reverse("backoffice:documents")).status_code == 200
    assert client.get(reverse("backoffice:documents_review")).status_code == 200
    assert client.get(reverse("backoffice:dashboard_compliance")).status_code == 200

    client.force_login(viewer)
    assert client.get(reverse("backoffice:documents")).status_code == 403
    assert client.get(reverse("backoffice:dashboard_compliance")).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_vehicle_document_model_supports_full_status_cycle(organization):
    vehicle = Vehicle.objects.create(organization=organization, plate="ABC1D23", vehicle_type="VAN")
    document = VehicleDocument.objects.create(
        vehicle=vehicle,
        document_type=VehicleDocumentType.CRLV.value,
        storage_key="vehicles/test/crlv.pdf",
        status=DocumentStatus.UNDER_REVIEW.value,
    )
    assert document.status == DocumentStatus.UNDER_REVIEW.value


@pytest.mark.django_db(transaction=True)
def test_carrier_document_model_exists(organization):
    carrier_org = Organization.objects.create(name="Carrier Org", type=OrganizationType.PARTNER)
    carrier = CarrierProfile.objects.create(
        organization=carrier_org,
        tenant=organization,
        email="carrier@example.com",
    )
    document = CarrierDocument.objects.create(
        carrier=carrier,
        document_type="CNPJ_CARD",
        storage_key="carriers/test/cnpj.pdf",
    )
    assert document.carrier_id == carrier.id


@pytest.mark.django_db(transaction=True)
def test_legacy_verify_driver_document_still_works(
    django_user_model, organization, tmp_path, settings
):
    settings.PRIVATE_DOCUMENT_STORAGE_ROOT = tmp_path
    actor = django_user_model.objects.create_user(username="legacy", password="safe-pass-123")
    driver = Driver.objects.create(organization=organization, full_name="Legacy")
    storage = PrivateDocumentStorageAdapter()
    document = add_driver_document(
        driver=driver,
        document_type=DriverDocumentType.DRIVER_LICENSE,
        storage=storage,
        content=BytesIO(b"%PDF-1.4"),
        filename="cnh.pdf",
        actor=actor,
        expiration_date=timezone.localdate() + timedelta(days=20),
    )
    verify_driver_document(document, actor=actor)
    document.refresh_from_db()
    assert document.status == DocumentStatus.APPROVED.value
