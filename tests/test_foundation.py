import uuid
from io import BytesIO, StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.core.management import call_command
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.audit.infrastructure.django.services import record_audit_event
from src.identity.application.services import (
    membership_has_permission,
    membership_scope_for_permission,
)
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.domain.rbac import ROLE_PERMISSIONS
from src.identity.infrastructure.django.models import (
    MembershipRole,
    Permission,
    Role,
    RolePermission,
)
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.infrastructure.django.logging import RequestIDLogFilter, sanitize_log_value
from src.shared.infrastructure.django.storage import PrivateDocumentStorageAdapter


@pytest.mark.django_db(transaction=True)
def test_user_uses_uuid_primary_key():
    user = get_user_model().objects.create_user(username="ana", password="safe-password-123")

    assert isinstance(user.id, uuid.UUID)


@pytest.mark.django_db(transaction=True)
def test_organization_membership_role_permission_and_scope():
    user = get_user_model().objects.create_user(username="bruno", password="safe-password-123")
    organization = Organization.objects.create(
        name="Rotta Transportes",
        type=OrganizationType.TRANSPORT_COMPANY,
    )
    membership = Membership.objects.create(user=user, organization=organization)
    permission = Permission.objects.create(
        code=PermissionCode.ORGANIZATIONS_VIEW,
        name="View organizations",
    )
    role = Role.objects.create(code=RoleCode.COMPANY_ADMIN, name="Company admin")
    RolePermission.objects.create(role=role, permission=permission)
    MembershipRole.objects.create(membership=membership, role=role, scope=AccessScope.COMPANY)

    assert membership.organization == organization
    assert membership_has_permission(membership, PermissionCode.ORGANIZATIONS_VIEW)
    assert (
        membership_scope_for_permission(membership, PermissionCode.ORGANIZATIONS_VIEW)
        == AccessScope.COMPANY
    )


@pytest.mark.django_db(transaction=True)
def test_missing_permission_returns_none_scope():
    user = get_user_model().objects.create_user(username="carla", password="safe-password-123")
    organization = Organization.objects.create(
        name="Cliente Exemplo", type=OrganizationType.CUSTOMER
    )
    membership = Membership.objects.create(user=user, organization=organization)

    assert not membership_has_permission(membership, PermissionCode.AUDIT_VIEW)
    assert (
        membership_scope_for_permission(membership, PermissionCode.AUDIT_VIEW) == AccessScope.NONE
    )


@pytest.mark.django_db(transaction=True)
def test_audit_log_is_created_and_sanitizes_secrets():
    user = get_user_model().objects.create_user(username="davi", password="safe-password-123")

    record_audit_event(
        action="user_updated",
        actor=user,
        target=user,
        after={"password": "plain-text", "profile": {"token": "abc", "name": "Davi"}},
    )

    audit_log = AuditLog.objects.get(action="user_updated")
    assert audit_log.after["password"] == "[REDACTED]"
    assert audit_log.after["profile"]["token"] == "[REDACTED]"
    assert audit_log.after["profile"]["name"] == "Davi"


@pytest.mark.django_db(transaction=True)
def test_basic_authentication_and_login_audit():
    user = get_user_model().objects.create_user(username="eva", password="safe-password-123")
    client = Client()

    assert client.login(username="eva", password="safe-password-123")

    request = RequestFactory().get(reverse("home"), HTTP_USER_AGENT="pytest")
    request.request_id = "test-request-id"
    user_logged_in.send(sender=user.__class__, request=request, user=user)

    assert AuditLog.objects.filter(
        action="login", actor=user, request_id="test-request-id"
    ).exists()


def test_request_id_middleware_adds_response_header():
    response = Client().get(reverse("home"))

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


@pytest.mark.django_db(transaction=True)
def test_bootstrap_rotta_creates_rbac_and_is_idempotent():
    RolePermission.objects.all().delete()
    Role.objects.all().delete()
    Permission.objects.all().delete()

    first_output = StringIO()
    second_output = StringIO()

    call_command("bootstrap_rotta", stdout=first_output)
    first_counts = (
        Role.objects.count(),
        Permission.objects.count(),
        RolePermission.objects.count(),
    )

    call_command("bootstrap_rotta", stdout=second_output)
    second_counts = (
        Role.objects.count(),
        Permission.objects.count(),
        RolePermission.objects.count(),
    )

    assert first_counts == second_counts
    assert Role.objects.filter(code=RoleCode.SYSTEM_ADMIN).exists()
    assert Permission.objects.filter(code=PermissionCode.AUDIT_VIEW).exists()
    assert "role_permissions_created" in first_output.getvalue()
    assert "role_permissions_unchanged" in second_output.getvalue()


@pytest.mark.django_db(transaction=True)
def test_bootstrap_role_permission_matrix_uses_least_privilege():
    call_command("bootstrap_rotta", stdout=StringIO())

    system_admin = Role.objects.get(code=RoleCode.SYSTEM_ADMIN)
    viewer = Role.objects.get(code=RoleCode.VIEWER)
    driver = Role.objects.get(code=RoleCode.DRIVER)

    assert set(system_admin.permissions.values_list("code", flat=True)) == {
        permission.value for permission in ROLE_PERMISSIONS[RoleCode.SYSTEM_ADMIN]
    }
    assert set(viewer.permissions.values_list("code", flat=True)) == {
        PermissionCode.ORGANIZATIONS_VIEW,
        PermissionCode.MEMBERSHIPS_VIEW,
    }
    assert not driver.permissions.filter(code=PermissionCode.AUDIT_VIEW).exists()
    assert not viewer.permissions.filter(code=PermissionCode.ROLES_MANAGE).exists()


@pytest.mark.django_db(transaction=True)
def test_healthcheck_returns_ok():
    response = Client().get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_request_id_rejects_invalid_incoming_header():
    response = Client().get(reverse("home"), HTTP_X_REQUEST_ID="not-a-valid-request-id")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "not-a-valid-request-id"
    uuid.UUID(response.headers["X-Request-ID"])


def test_request_id_accepts_valid_uuid_header():
    request_id = str(uuid.uuid4())
    response = Client().get(reverse("home"), HTTP_X_REQUEST_ID=request_id)

    assert response.headers["X-Request-ID"] == request_id


def test_logging_filter_adds_request_id_field():
    class Record:
        pass

    record = Record()

    assert RequestIDLogFilter().filter(record)
    assert record.request_id


def test_log_sanitization_redacts_sensitive_values():
    payload = {
        "password": "secret",
        "token": "secret",
        "secret": "secret",
        "api_key": "secret",
        "authorization": "Bearer secret",
        "credential": "secret",
        "safe": "visible",
    }

    sanitized = sanitize_log_value(payload)

    assert sanitized["safe"] == "visible"
    for key in ("password", "token", "secret", "api_key", "authorization", "credential"):
        assert sanitized[key] == "[REDACTED]"


@pytest.mark.django_db(transaction=True)
def test_audit_sanitizes_all_sensitive_keys():
    user = get_user_model().objects.create_user(username="sara", password="safe-password-123")

    record_audit_event(
        action="user_updated",
        actor=user,
        target=user,
        metadata={
            "password": "secret",
            "token": "secret",
            "secret": "secret",
            "api_key": "secret",
            "authorization": "Bearer secret",
            "credential": "secret",
        },
    )

    audit_log = AuditLog.objects.filter(action="user_updated", actor=user).latest("created_at")

    for key in ("password", "token", "secret", "api_key", "authorization", "credential"):
        assert audit_log.metadata[key] == "[REDACTED]"


@pytest.mark.django_db(transaction=True)
def test_role_removed_is_audited():
    user = get_user_model().objects.create_user(username="tiago", password="safe-password-123")
    organization = Organization.objects.create(
        name="Rotta",
        type=OrganizationType.TRANSPORT_COMPANY,
    )
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.create(code="TEMP_ROLE", name="Temporary role")
    membership_role = MembershipRole.objects.create(
        membership=membership,
        role=role,
        scope=AccessScope.COMPANY,
    )

    membership_role.delete()

    assert AuditLog.objects.filter(
        action="role_removed",
        organization=organization,
        target_id=str(membership.id),
    ).exists()


def test_private_document_storage_adapter(tmp_path):
    with override_settings(PRIVATE_DOCUMENT_STORAGE_ROOT=tmp_path):
        storage = PrivateDocumentStorageAdapter()
        saved_path = storage.save("drivers/cnh.txt", BytesIO(b"private"))

        assert storage.exists(saved_path)
        with storage.open(saved_path) as stored_file:
            assert stored_file.read() == b"private"
        storage.delete(saved_path)
        assert not storage.exists(saved_path)


def test_private_document_storage_rejects_unsafe_paths(tmp_path):
    with override_settings(PRIVATE_DOCUMENT_STORAGE_ROOT=tmp_path):
        storage = PrivateDocumentStorageAdapter()

        with pytest.raises(ValueError):
            storage.save("../outside.txt", BytesIO(b"bad"))
        with pytest.raises(NotImplementedError):
            storage.url("drivers/cnh.txt")
