from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.identity.application.services import (
    create_user_with_membership,
    update_user_details,
    update_user_membership,
)
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.application.services import (
    create_branch,
    create_business_unit,
    create_department,
    create_team,
)
from src.organizations.domain.enums import MembershipStatus, OrganizationType
from src.organizations.infrastructure.django.models import (
    Membership,
    Organization,
)
from src.shared.domain.enums import AccessScope
from src.shared.interfaces.backoffice.authorization import (
    scoped_business_unit_queryset,
)


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
    return Organization.objects.create(
        name="Outra Transportes",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.mark.django_db(transaction=True)
def test_user_lifecycle_service_and_auditing(organization, rbac_ready, django_user_model):
    operator = django_user_model.objects.create_user(username="operator", password="pass")
    role = Role.objects.get(code=RoleCode.SALESPERSON.value)

    # 1. Create user with membership
    user = create_user_with_membership(
        username="newoperator",
        email="operator@test.com",
        first_name="New",
        last_name="Op",
        password="safe-password-123",
        organization=organization,
        role=role,
        scope=AccessScope.COMPANY.value,
        actor=operator,
    )

    assert user.username == "newoperator"
    assert user.email == "operator@test.com"
    assert user.is_active is True

    # Validate audit events
    assert AuditLog.objects.filter(action="user_created", target_id=str(user.id)).exists()
    created_audit = AuditLog.objects.get(action="user_created", target_id=str(user.id))
    assert created_audit.actor == operator
    assert created_audit.after["username"] == "[REDACTED]"
    assert created_audit.after["email"] == "[REDACTED]"

    assert AuditLog.objects.filter(
        action="user_membership_changed", target_id=str(user.id)
    ).exists()

    # 2. Update user details
    update_user_details(
        user,
        email="newop@test.com",
        first_name="Real",
        last_name="Name",
        is_active=False,
        actor=operator,
    )
    user.refresh_from_db()
    assert user.is_active is False
    assert user.first_name == "Real"

    assert AuditLog.objects.filter(action="user_updated", target_id=str(user.id)).exists()
    assert AuditLog.objects.filter(action="user_deactivated", target_id=str(user.id)).exists()


@pytest.mark.django_db(transaction=True)
def test_user_membership_change(organization, other_organization, rbac_ready, django_user_model):
    operator = django_user_model.objects.create_user(username="operator", password="pass")
    user = django_user_model.objects.create_user(username="testuser", password="pass")
    role = Role.objects.get(code=RoleCode.SALESPERSON.value)

    # Assign membership to organization
    update_user_membership(
        user, organization=organization, role=role, scope=AccessScope.COMPANY.value, actor=operator
    )
    assert user.memberships.filter(
        organization=organization, status=MembershipStatus.ACTIVE.value
    ).exists()

    # Shift membership parameters (role/scope update)
    admin_role = Role.objects.get(code=RoleCode.COMPANY_ADMIN.value)
    update_user_membership(
        user,
        organization=organization,
        role=admin_role,
        scope=AccessScope.ALL.value,
        actor=operator,
    )

    membership = user.memberships.get(organization=organization)
    binding = MembershipRole.objects.get(membership=membership)
    assert binding.role == admin_role
    assert binding.scope == AccessScope.ALL.value

    assert AuditLog.objects.filter(action="user_role_changed", target_id=str(user.id)).exists()


@pytest.mark.django_db
def test_hierarchy_validation_rules(organization, other_organization):
    bu1 = create_business_unit(organization=organization, name="BU A")
    bu_other = create_business_unit(organization=other_organization, name="BU Other")

    # Branch validation
    with pytest.raises(ValidationError) as excinfo:
        create_branch(organization=organization, business_unit=bu_other, name="Branch Mismatch")
    assert "business_unit" in excinfo.value.message_dict

    branch1 = create_branch(organization=organization, business_unit=bu1, name="Branch Valid")

    # Department validation
    branch_other = create_branch(organization=other_organization, name="Branch Other")
    with pytest.raises(ValidationError) as excinfo:
        create_department(organization=organization, branch=branch_other, name="Dept Mismatch")
    assert "branch" in excinfo.value.message_dict

    create_department(organization=organization, branch=branch1, name="Dept Valid")

    # Team validation
    dept_other = create_department(organization=other_organization, name="Dept Other")
    with pytest.raises(ValidationError) as excinfo:
        create_team(organization=organization, department=dept_other, name="Team Mismatch")
    assert "department" in excinfo.value.message_dict


@pytest.mark.django_db
def test_scoping_isolation_helpers(organization, other_organization, rbac_ready, django_user_model):
    org_admin = django_user_model.objects.create_user(username="org_admin", password="pass")
    grant(org_admin, organization, RoleCode.COMPANY_ADMIN, AccessScope.COMPANY)

    other_admin = django_user_model.objects.create_user(username="other_admin", password="pass")
    grant(other_admin, other_organization, RoleCode.COMPANY_ADMIN, AccessScope.COMPANY)

    # Create BU per organization
    bu_org = create_business_unit(organization=organization, name="BU Org")
    bu_other = create_business_unit(organization=other_organization, name="BU Other")

    # Test scoping for org_admin
    queryset = scoped_business_unit_queryset(org_admin, PermissionCode.ORGANIZATIONS_VIEW)
    assert bu_org in queryset
    assert bu_other not in queryset

    # Test scoping for other_admin
    queryset_other = scoped_business_unit_queryset(other_admin, PermissionCode.ORGANIZATIONS_VIEW)
    assert bu_org not in queryset_other
    assert bu_other in queryset_other


@pytest.mark.django_db(transaction=True)
def test_backoffice_user_and_org_security_views(
    client, django_user_model, organization, rbac_ready
):
    admin_user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    grant(admin_user, organization, RoleCode.COMPANY_ADMIN, AccessScope.COMPANY)

    viewer_user = django_user_model.objects.create_user(username="viewer", password="safe-pass-123")
    grant(viewer_user, organization, RoleCode.VIEWER, AccessScope.COMPANY)

    # 1. Anonymous redirected to login
    response = client.get(reverse("backoffice:users"))
    assert response.status_code == 302

    # 2. View user list with permission
    client.force_login(admin_user)
    response = client.get(reverse("backoffice:users"), HTTP_HOST="localhost")
    assert response.status_code == 200

    # 3. Viewer user cannot create new user
    client.force_login(viewer_user)
    response = client.get(reverse("backoffice:user_create"), HTTP_HOST="localhost")
    assert response.status_code == 403

    # 4. Admin creates new user via POST
    client.force_login(admin_user)
    role = Role.objects.get(code=RoleCode.SALESPERSON.value)
    response = client.post(
        reverse("backoffice:user_create"),
        {
            "username": "newpostuser",
            "email": "newpostuser@rotta.com",
            "first_name": "Post",
            "last_name": "User",
            "password": "super-strong-password-1",
            "organization": str(organization.id),
            "role": str(role.id),
            "scope": "COMPANY",
        },
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    created_user = django_user_model.objects.get(username="newpostuser")
    assert response["Location"] == reverse("backoffice:user_detail", args=[created_user.id])
