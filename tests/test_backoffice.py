import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.audit.infrastructure.django.services import record_audit_event
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Rotta Transportes",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization():
    return Organization.objects.create(name="Outra Empresa", type=OrganizationType.CUSTOMER)


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


def test_public_home_still_renders(client):
    response = client.get(reverse("public:home"))

    assert response.status_code == 200
    assert any(template.name == "public/home.html" for template in response.templates)


def test_backoffice_dashboard_requires_authentication(client):
    response = client.get(reverse("backoffice:dashboard"))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("backoffice:login"))


def test_backoffice_users_requires_authentication(client):
    response = client.get(reverse("backoffice:users"))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("backoffice:login"))


@pytest.mark.django_db
def test_backoffice_login_valid_user_redirects_to_dashboard(client, django_user_model):
    django_user_model.objects.create_user(username="operator", password="safe-pass-123")

    response = client.post(
        reverse("backoffice:login"),
        {"username": "operator", "password": "safe-pass-123"},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("backoffice:dashboard")


@pytest.mark.django_db
def test_backoffice_dashboard_authenticated_uses_real_foundation_template(
    client, django_user_model, rbac_ready, organization
):
    user = django_user_model.objects.create_user(username="operator", password="safe-pass-123")
    grant(user, organization, RoleCode.COMPANY_ADMIN)
    client.force_login(user)

    response = client.get(reverse("backoffice:dashboard"))

    assert response.status_code == 200
    assert any(template.name == "backoffice/dashboard.html" for template in response.templates)
    assert b"Organizations" in response.content
    assert b"Revenue" not in response.content
    assert b"backoffice/nexadash/css/style.css" in response.content


@pytest.mark.django_db
def test_backoffice_logout_returns_to_login(client, django_user_model):
    user = django_user_model.objects.create_user(username="operator", password="safe-pass-123")
    client.force_login(user)

    response = client.post(reverse("backoffice:logout"))

    assert response.status_code == 302
    assert response["Location"] == reverse("backoffice:login")


@pytest.mark.django_db
def test_authenticated_without_permission_gets_403_for_users_and_audit(client, django_user_model):
    user = django_user_model.objects.create_user(username="viewer", password="safe-pass-123")
    client.force_login(user)

    assert client.get(reverse("backoffice:users")).status_code == 403
    assert client.get(reverse("backoffice:audit")).status_code == 403


@pytest.mark.django_db
def test_backoffice_foundation_lists_return_200_with_permission(
    client, django_user_model, rbac_ready, organization
):
    user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    grant(user, organization, RoleCode.COMPANY_ADMIN)
    client.force_login(user)

    route_names = [
        "backoffice:users",
        "backoffice:organizations",
        "backoffice:memberships",
        "backoffice:audit",
        "backoffice:roles",
        "backoffice:permissions",
    ]

    for route_name in route_names:
        response = client.get(reverse(route_name))
        assert response.status_code == 200, route_name


@pytest.mark.django_db
def test_organization_scope_limits_visible_organizations(
    client, django_user_model, rbac_ready, organization, other_organization
):
    user = django_user_model.objects.create_user(username="scoped", password="safe-pass-123")
    grant(user, organization, RoleCode.VIEWER, AccessScope.COMPANY)
    client.force_login(user)

    response = client.get(reverse("backoffice:organizations"))

    assert response.status_code == 200
    assert organization.name.encode() in response.content
    assert other_organization.name.encode() not in response.content


@pytest.mark.django_db
def test_organization_detail_outside_scope_returns_404(
    client, django_user_model, rbac_ready, organization, other_organization
):
    user = django_user_model.objects.create_user(username="scoped", password="safe-pass-123")
    grant(user, organization, RoleCode.VIEWER, AccessScope.COMPANY)
    client.force_login(user)

    response = client.get(reverse("backoffice:organization_detail", args=[other_organization.id]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_user_list_filter_and_detail(client, django_user_model, rbac_ready, organization):
    user = django_user_model.objects.create_user(
        username="admin", email="admin@example.com", password="safe-pass-123"
    )
    visible = django_user_model.objects.create_user(
        username="ana", email="ana@example.com", password="safe-pass-123"
    )
    hidden = django_user_model.objects.create_user(
        username="bia", email="bia@example.com", password="safe-pass-123"
    )
    grant(user, organization, RoleCode.COMPANY_ADMIN)
    Membership.objects.create(user=visible, organization=organization)
    client.force_login(user)

    response = client.get(reverse("backoffice:users"), {"email": "ana"})

    assert response.status_code == 200
    assert b"ana@example.com" in response.content
    assert b"bia@example.com" not in response.content

    detail = client.get(reverse("backoffice:user_detail", args=[visible.id]))
    hidden_detail = client.get(reverse("backoffice:user_detail", args=[hidden.id]))

    assert detail.status_code == 200
    assert hidden_detail.status_code == 404


@pytest.mark.django_db
def test_membership_list_filter_and_detail(client, django_user_model, rbac_ready, organization):
    user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    member = django_user_model.objects.create_user(username="member", password="safe-pass-123")
    grant(user, organization, RoleCode.COMPANY_ADMIN)
    membership = Membership.objects.create(user=member, organization=organization)
    client.force_login(user)

    response = client.get(reverse("backoffice:memberships"), {"user": "member"})
    detail = client.get(reverse("backoffice:membership_detail", args=[membership.id]))

    assert response.status_code == 200
    assert b"member" in response.content
    assert detail.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_roles_permissions_and_audit_detail(client, django_user_model, rbac_ready, organization):
    user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    grant(user, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)
    record_audit_event(
        action="user_updated",
        actor=user,
        organization=organization,
        target=user,
        metadata={"password": "secret", "safe": "visible"},
    )
    client.force_login(user)

    role = Role.objects.get(code=RoleCode.COMPANY_ADMIN)
    role_detail = client.get(reverse("backoffice:role_detail", args=[role.id]))
    permissions = client.get(reverse("backoffice:permissions"))
    audit = AuditLog.objects.filter(action="user_updated", metadata__safe="visible").latest(
        "created_at"
    )
    audit_list = client.get(reverse("backoffice:audit"), {"action": "user_updated"})
    audit_detail = client.get(reverse("backoffice:audit_detail", args=[audit.id]))

    assert role_detail.status_code == 200
    assert PermissionCode.USERS_VIEW.encode() in role_detail.content
    assert permissions.status_code == 200
    assert b"users.view" in permissions.content
    assert audit_list.status_code == 200
    assert b"user_updated" in audit_list.content
    assert audit_detail.status_code == 200
    assert b"[REDACTED]" in audit_detail.content
    assert b"secret" not in audit_detail.content


@pytest.mark.django_db
def test_list_pagination(client, django_user_model, rbac_ready, organization):
    user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    grant(user, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)
    for index in range(30):
        Organization.objects.create(name=f"Empresa {index:02d}", type=OrganizationType.CUSTOMER)
    client.force_login(user)

    response = client.get(reverse("backoffice:organizations"))

    assert response.status_code == 200
    assert b"1 / 2" in response.content


def test_backoffice_sidebar_real_links_are_resolvable(client):
    response = client.get(reverse("backoffice:login"))

    assert response.status_code == 200
    assert reverse("backoffice:dashboard")
    assert reverse("backoffice:dashboard_operations")
    assert reverse("backoffice:dashboard_relationship")
    assert reverse("backoffice:dashboard_finance")
    assert reverse("backoffice:dashboard_analytics")
    assert reverse("backoffice:dashboard_commercial")
    assert reverse("backoffice:dashboard_marketplace")
    assert reverse("backoffice:dashboard_compliance")
    assert reverse("backoffice:dashboard_fleet_health")
    assert reverse("backoffice:organizations")
    assert reverse("backoffice:drivers")
    assert reverse("backoffice:vehicles")
    assert reverse("backoffice:carriers")
    assert reverse("backoffice:users")
    assert reverse("backoffice:memberships")
    assert reverse("backoffice:roles")
    assert reverse("backoffice:permissions")
    assert reverse("backoffice:audit")
    assert reverse("backoffice:documents")
    assert reverse("backoffice:documents_review")
    assert reverse("backoffice:document_upload")


@pytest.mark.django_db
def test_dashboard_thematic_routes_require_authentication(client):
    route_names = [
        "backoffice:dashboard",
        "backoffice:dashboard_operations",
        "backoffice:dashboard_relationship",
        "backoffice:dashboard_finance",
        "backoffice:dashboard_analytics",
        "backoffice:dashboard_commercial",
        "backoffice:dashboard_marketplace",
        "backoffice:dashboard_compliance",
        "backoffice:dashboard_fleet_health",
    ]
    for route_name in route_names:
        response = client.get(reverse(route_name))
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("backoffice:login"))


@pytest.mark.django_db
def test_dashboard_thematic_routes_enforce_rbac(
    client, django_user_model, rbac_ready, organization
):
    admin = django_user_model.objects.create_user(username="dashadmin", password="safe-pass-123")
    viewer = django_user_model.objects.create_user(username="dashviewer", password="safe-pass-123")
    outsider = django_user_model.objects.create_user(
        username="dashoutsider", password="safe-pass-123"
    )
    grant(admin, organization, RoleCode.COMPANY_ADMIN)
    grant(viewer, organization, RoleCode.VIEWER)

    client.force_login(admin)
    allowed_for_admin = [
        "backoffice:dashboard",
        "backoffice:dashboard_operations",
        "backoffice:dashboard_relationship",
        "backoffice:dashboard_finance",
        "backoffice:dashboard_analytics",
        "backoffice:dashboard_commercial",
        "backoffice:dashboard_marketplace",
        "backoffice:dashboard_compliance",
        "backoffice:dashboard_fleet_health",
    ]
    for route_name in allowed_for_admin:
        assert client.get(reverse(route_name)).status_code == 200

    client.force_login(outsider)
    assert client.get(reverse("backoffice:dashboard")).status_code == 200
    denied_for_viewer = [
        "backoffice:dashboard_operations",
        "backoffice:dashboard_relationship",
        "backoffice:dashboard_finance",
        "backoffice:dashboard_analytics",
        "backoffice:dashboard_commercial",
        "backoffice:dashboard_marketplace",
        "backoffice:dashboard_compliance",
        "backoffice:dashboard_fleet_health",
    ]
    for route_name in denied_for_viewer:
        assert client.get(reverse(route_name)).status_code == 403


def test_backoffice_detail_404_for_unknown_uuid(
    client, django_user_model, rbac_ready, organization
):
    user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    grant(user, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)
    client.force_login(user)

    response = client.get(reverse("backoffice:organization_detail", args=[uuid.uuid4()]))

    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_backoffice_login_invalid_credentials_stays_on_login_with_generic_message(
    client, django_user_model
):
    django_user_model.objects.create_user(username="operator", password="safe-pass-123")

    response = client.post(
        reverse("backoffice:login"),
        {"username": "operator", "password": "wrong-pass"},
    )

    assert response.status_code == 200
    assert "Usuário ou senha inválidos.".encode() in response.content
    assert "_auth_user_id" not in client.session
    assert AuditLog.objects.filter(action="login_failed").exists()
    audit = AuditLog.objects.filter(action="login_failed").latest("created_at")
    assert audit.metadata["username"] == "operator"
    assert "password" not in audit.metadata


@pytest.mark.django_db(transaction=True)
def test_backoffice_unknown_user_login_is_denied_and_audited(client):
    response = client.post(
        reverse("backoffice:login"),
        {"username": "unknown", "password": "wrong-pass"},
    )

    assert response.status_code == 200
    assert "Usuário ou senha inválidos.".encode() in response.content
    assert "_auth_user_id" not in client.session
    assert AuditLog.objects.filter(action="login_failed").exists()


@pytest.mark.django_db(transaction=True)
def test_backoffice_logout_clears_session_and_private_page_requires_login(
    client, django_user_model
):
    user = django_user_model.objects.create_user(username="operator", password="safe-pass-123")
    client.force_login(user)

    logout_response = client.post(reverse("backoffice:logout"))
    dashboard_response = client.get(reverse("backoffice:dashboard"))

    assert logout_response.status_code == 302
    assert logout_response["Location"] == reverse("backoffice:login")
    assert dashboard_response.status_code == 302
    assert dashboard_response["Location"].startswith(reverse("backoffice:login"))
    assert AuditLog.objects.filter(action="logout", actor=user).exists()
