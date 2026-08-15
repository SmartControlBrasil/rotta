import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.test import Client, RequestFactory
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.audit.infrastructure.django.services import record_audit_event
from src.identity.application.services import (
    membership_has_permission,
    membership_scope_for_permission,
)
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import (
    MembershipRole,
    Permission,
    Role,
    RolePermission,
)
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope


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
    client = Client()

    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
