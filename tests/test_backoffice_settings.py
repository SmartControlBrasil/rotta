import pytest
from io import StringIO
from django.core.management import call_command
from django.urls import reverse
from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole

def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization, status="ACTIVE")
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership

@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())

@pytest.fixture
def org_a(db):
    return Organization.objects.create(
        name="Transportadora A",
        type=OrganizationType.TRANSPORT_COMPANY,
        document="12345678000199",
    )

@pytest.fixture
def org_b(db):
    return Organization.objects.create(
        name="Transportadora B",
        type=OrganizationType.TRANSPORT_COMPANY,
        document="98765432000188",
    )

@pytest.fixture
def user_admin(db, django_user_model):
    return django_user_model.objects.create_user(username="adminuser", password="password")

@pytest.fixture
def user_viewer(db, django_user_model):
    return django_user_model.objects.create_user(username="vieweruser", password="password")

@pytest.fixture
def user_unauthorized(db, django_user_model):
    return django_user_model.objects.create_user(username="unauthuser", password="password")

@pytest.mark.django_db
def test_settings_views_require_authentication(client):
    urls = [
        "backoffice:setting_overview",
        "backoffice:setting_organization",
        "backoffice:setting_structure",
        "backoffice:setting_access",
        "backoffice:setting_operation",
        "backoffice:setting_marketplace",
        "backoffice:setting_thermal",
        "backoffice:setting_notifications",
        "backoffice:setting_integrations",
        "backoffice:setting_security",
    ]
    for url_name in urls:
        response = client.get(reverse(url_name))
        assert response.status_code == 302
        assert "login" in response.url

@pytest.mark.django_db
def test_settings_views_access_denied_without_permission(rbac_ready, client, org_a, user_unauthorized):
    # Grant a membership but clear all roles to ensure zero permissions
    grant(user_unauthorized, org_a, "VIEWER", scope=AccessScope.COMPANY)
    MembershipRole.objects.all().delete()
    client.force_login(user_unauthorized)
    
    urls = [
        "backoffice:setting_overview",
        "backoffice:setting_organization",
        "backoffice:setting_structure",
        "backoffice:setting_access",
        "backoffice:setting_operation",
        "backoffice:setting_marketplace",
        "backoffice:setting_thermal",
        "backoffice:setting_notifications",
        "backoffice:setting_integrations",
        "backoffice:setting_security",
    ]
    # Delete all membership roles to ensure zero permissions
    MembershipRole.objects.all().delete()
    
    for url_name in urls:
        response = client.get(reverse(url_name))
        assert response.status_code == 403

@pytest.mark.django_db
def test_settings_views_allowed_with_permission(rbac_ready, client, org_a, user_viewer):
    grant(user_viewer, org_a, "VIEWER", scope=AccessScope.COMPANY)
    client.force_login(user_viewer)
    
    urls = [
        "backoffice:setting_overview",
        "backoffice:setting_organization",
        "backoffice:setting_structure",
        "backoffice:setting_access",
        "backoffice:setting_operation",
        "backoffice:setting_marketplace",
        "backoffice:setting_thermal",
        "backoffice:setting_notifications",
        "backoffice:setting_integrations",
        "backoffice:setting_security",
    ]
    for url_name in urls:
        response = client.get(reverse(url_name))
        assert response.status_code == 200

@pytest.mark.django_db
def test_organization_settings_scoping_and_update(rbac_ready, client, org_a, org_b, user_admin, user_viewer):
    # user_admin is COMPANY_ADMIN of org_a
    grant(user_admin, org_a, "COMPANY_ADMIN", scope=AccessScope.COMPANY)
    # user_viewer is VIEWER of org_a
    grant(user_viewer, org_a, "VIEWER", scope=AccessScope.COMPANY)
    
    # 1. user_viewer (VIEWER) has settings.view but NOT settings.update. Form fields must be disabled
    client.force_login(user_viewer)
    response = client.get(reverse("backoffice:setting_organization"))
    assert response.status_code == 200
    assert response.context["can_edit"] is False
    assert response.context["form"].fields["name"].disabled is True
    
    # Post should raise 403
    response = client.post(reverse("backoffice:setting_organization"), {
        "name": "Novo Nome Fantasia",
        "legal_name": "Nova Razao Social",
        "document": "12345678000199",
        "type": "TRANSPORT_COMPANY",
        "is_active": True,
    })
    assert response.status_code == 403
    
    # 2. user_admin (COMPANY_ADMIN) has settings.update. Form fields should not be disabled
    client.force_login(user_admin)
    response = client.get(reverse("backoffice:setting_organization") + f"?org_id={org_a.id}")
    assert response.status_code == 200
    assert response.context["can_edit"] is True
    assert not response.context["form"].fields["name"].disabled
    
    # Post should succeed and update org_a
    response = client.post(reverse("backoffice:setting_organization") + f"?org_id={org_a.id}", {
        "name": "Nome Fantasia Novo A",
        "legal_name": "Nova Razao Social A",
        "document": "12345678000199",
        "type": "TRANSPORT_COMPANY",
        "is_active": True,
    })
    assert response.status_code == 302
    org_a.refresh_from_db()
    assert org_a.name == "Nome Fantasia Novo A"
    assert org_a.legal_name == "Nova Razao Social A"
    
    # 3. user_admin tries to view/update org_b where they have no membership
    response = client.get(reverse("backoffice:setting_organization") + f"?org_id={org_b.id}")
    assert response.status_code == 404
    
    response = client.post(reverse("backoffice:setting_organization") + f"?org_id={org_b.id}", {
        "name": "Nome Fantasia Novo B",
        "legal_name": "Nova Razao Social B",
        "document": "98765432000188",
        "type": "TRANSPORT_COMPANY",
        "is_active": True,
    })
    assert response.status_code == 404

@pytest.mark.django_db
def test_secrets_protection_in_templates(rbac_ready, client, org_a, user_viewer):
    grant(user_viewer, org_a, "VIEWER", scope=AccessScope.COMPANY)
    client.force_login(user_viewer)
    
    # Get integrations settings and assert secret tokens are masked/truncated
    response = client.get(reverse("backoffice:setting_integrations"))
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    
    # Ensure no raw secret key/unmasked sensitive data appears
    assert "rot_live_" in html
    assert "rot_live_••••••••••••••••••••3a9c" in html
    # Assume actual keys or database details are not present
    assert "SECRET_KEY" not in html
    assert "unsafe-local-development-key-change-me" not in html
