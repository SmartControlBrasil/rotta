import uuid
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.customers.application.services import (
    CustomerData,
    assign_customer_owner,
    change_customer_status,
    register_customer,
    update_customer,
)
from src.customers.domain.enums import CustomerStatus, CustomerType
from src.customers.infrastructure.django.models import Customer
from src.identity.domain.enums import RoleCode
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
    return Organization.objects.create(
        name="Outra Empresa",
        type=OrganizationType.CUSTOMER,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.mark.django_db
def test_customer_model_validation(organization):
    # Valid individual customer (CPF)
    ind = Customer(
        organization=organization,
        customer_type=CustomerType.INDIVIDUAL,
        legal_name="João Silva",
        document_number="111.444.777-35",
        email="joao@example.com",
    )
    ind.full_clean()
    ind.save()
    assert ind.document_number == "11144477735"

    # Valid company customer (CNPJ)
    comp = Customer(
        organization=organization,
        customer_type=CustomerType.COMPANY,
        legal_name="Empresa A LTDA",
        document_number="11.222.333/0001-81",
        email="contato@empresa.com",
    )
    comp.full_clean()
    comp.save()
    assert comp.document_number == "11222333000181"

    # Invalid CPF
    ind_invalid = Customer(
        organization=organization,
        customer_type=CustomerType.INDIVIDUAL,
        legal_name="João Invalido",
        document_number="111.444.777-00",
        email="joao@example.com",
    )
    with pytest.raises(ValidationError) as excinfo:
        ind_invalid.full_clean()
    assert "document_number" in excinfo.value.message_dict

    # Invalid CNPJ
    comp_invalid = Customer(
        organization=organization,
        customer_type=CustomerType.COMPANY,
        legal_name="Empresa Invalida",
        document_number="11.222.333/0001-00",
        email="contato@empresa.com",
    )
    with pytest.raises(ValidationError) as excinfo:
        comp_invalid.full_clean()
    assert "document_number" in excinfo.value.message_dict


@pytest.mark.django_db
def test_customer_uniqueness_per_organization(organization, other_organization):
    Customer.objects.create(
        organization=organization,
        customer_type=CustomerType.INDIVIDUAL,
        legal_name="Cliente Um",
        document_number="11144477735",
        email="um@example.com",
    )

    # Duplicating in the same organization is blocked
    dup = Customer(
        organization=organization,
        customer_type=CustomerType.INDIVIDUAL,
        legal_name="Cliente Dois",
        document_number="11144477735",
        email="dois@example.com",
    )
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            dup.save()

    # But it is allowed in a different organization (multi-tenant)
    other = Customer(
        organization=other_organization,
        customer_type=CustomerType.INDIVIDUAL,
        legal_name="Cliente Tres",
        document_number="11144477735",
        email="tres@example.com",
    )
    other.save()
    assert other.pk is not None


@pytest.mark.django_db(transaction=True)
def test_customer_creation_service_and_audit(organization, django_user_model):
    operator = django_user_model.objects.create_user(username="operator", password="pass")

    data = CustomerData(
        organization=organization,
        customer_type=CustomerType.COMPANY,
        legal_name="Embarcador Real",
        document_number="11.222.333/0001-81",
        email="contato@real.com",
    )

    customer = register_customer(data=data, actor=operator)

    assert customer.status == CustomerStatus.PROSPECT

    # Audit log validation
    assert AuditLog.objects.filter(action="customer_created", target_id=str(customer.id)).exists()
    audit = AuditLog.objects.filter(action="customer_created", target_id=str(customer.id)).first()
    assert audit.actor == operator
    # LGPD Redaction Check
    assert audit.after["document_number"] == "[REDACTED]"
    assert audit.after["email"] == "[REDACTED]"


@pytest.mark.django_db(transaction=True)
def test_customer_updates_and_status_changes(organization, django_user_model):
    operator = django_user_model.objects.create_user(username="operator", password="pass")

    data = CustomerData(
        organization=organization,
        customer_type=CustomerType.COMPANY,
        legal_name="Embarcador Real",
        document_number="11.222.333/0001-81",
        email="contato@real.com",
    )
    customer = register_customer(data=data, actor=operator)

    # Update customer data
    update_customer(customer, actor=operator, legal_name="Real S.A.", city="São Paulo", state="SP")
    customer.refresh_from_db()
    assert customer.legal_name == "Real S.A."
    assert customer.city == "São Paulo"

    # Verify update audit log
    assert AuditLog.objects.filter(action="customer_updated", target_id=str(customer.id)).exists()

    # Change status
    change_customer_status(customer, status=CustomerStatus.ACTIVE, actor=operator)
    customer.refresh_from_db()
    assert customer.status == CustomerStatus.ACTIVE
    assert AuditLog.objects.filter(
        action="customer_status_changed", target_id=str(customer.id)
    ).exists()

    # Assign owner
    salesperson = django_user_model.objects.create_user(username="seller", password="pass")
    assign_customer_owner(customer, owner=salesperson, actor=operator)
    customer.refresh_from_db()
    assert customer.owner == salesperson
    assert AuditLog.objects.filter(
        action="customer_owner_changed", target_id=str(customer.id)
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_backoffice_customer_views_security(client, django_user_model, organization, rbac_ready):
    # Setup users
    admin_user = django_user_model.objects.create_user(username="admin", password="safe-pass-123")
    grant(admin_user, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)

    unauthorized_user = django_user_model.objects.create_user(
        username="viewer", password="safe-pass-123"
    )
    grant(unauthorized_user, organization, RoleCode.VIEWER, AccessScope.COMPANY)

    # 1. Anonymous access is denied
    response = client.get(reverse("backoffice:customers"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("backoffice:login"))

    # 2. Unauthorized user gets 403 on lists
    client.force_login(unauthorized_user)
    response = client.get(reverse("backoffice:customers"), HTTP_HOST="localhost")
    assert response.status_code == 403

    # 3. Authorized admin can view list
    client.force_login(admin_user)
    response = client.get(reverse("backoffice:customers"), HTTP_HOST="localhost")
    assert response.status_code == 200

    # 4. Create customer via POST
    response = client.post(
        reverse("backoffice:customer_create"),
        {
            "customer_type": "COMPANY",
            "legal_name": "Cliente Admin",
            "document_number": "11.222.333/0001-81",
            "email": "admin@cliente.com",
            "organization": str(organization.id),
        },
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    customer = Customer.objects.get(legal_name="Cliente Admin")
    assert response["Location"] == reverse("backoffice:customer_detail", args=[customer.id])

    # 5. Detail View
    response = client.get(
        reverse("backoffice:customer_detail", args=[customer.id]), HTTP_HOST="localhost"
    )
    assert response.status_code == 200

    # 6. Status change
    response = client.post(
        reverse("backoffice:customer_status", args=[customer.id]),
        {"action": "ACTIVE"},
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.status == CustomerStatus.ACTIVE

    # 7. Non-existent UUID returns 404
    fake_id = uuid.uuid4()
    response = client.get(
        reverse("backoffice:customer_detail", args=[fake_id]), HTTP_HOST="localhost"
    )
    assert response.status_code == 404
