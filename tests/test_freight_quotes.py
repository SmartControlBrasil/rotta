import uuid
from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from src.audit.infrastructure.django.models import AuditLog
from src.customers.application.services import CustomerData, register_customer
from src.customers.domain.enums import CustomerType
from src.freights.application.quote_services import (
    ChargeData,
    FreightQuoteData,
    approve_freight_quote,
    create_freight_quote,
    revise_freight_quote,
    send_freight_quote,
    submit_freight_quote_for_review,
)
from src.freights.application.services import (
    CargoData,
    FreightRequestData,
    StopData,
    change_freight_request_status,
    create_freight_request,
    submit_freight_request,
)
from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightRequestStatus,
    FreightStopType,
)
from src.freights.domain.pricing import charge_line_total
from src.freights.domain.quote_enums import (
    FreightQuoteChargeType,
    FreightQuoteStatus,
)
from src.freights.domain.quote_state_machine import can_transition_quote
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.interfaces.backoffice.authorization import (
    scoped_freight_quote_queryset,
    user_has_backoffice_permission,
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
        name="Outra Empresa",
        type=OrganizationType.CUSTOMER,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


def make_customer(organization):
    return register_customer(
        data=CustomerData(
            organization=organization,
            customer_type=CustomerType.COMPANY,
            legal_name="Cliente Teste",
            document_number="11.222.333/0001-81",
            email="cliente@example.com",
        )
    )


def submitted_request(*, organization, user, customer):
    request = create_freight_request(
        data=FreightRequestData(
            organization=organization,
            customer=customer,
            created_by=user,
            stops=(
                StopData(stop_type=FreightStopType.PICKUP, sequence=1, city="SP", state="SP"),
                StopData(stop_type=FreightStopType.DELIVERY, sequence=2, city="RJ", state="RJ"),
            ),
            cargo=CargoData(
                description="Carga",
                weight_kg=Decimal("1000"),
                cargo_profile=FreightCargoProfile.DRY_CARGO,
            ),
        ),
        actor=user,
    )
    submit_freight_request(request, actor=user)
    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=user)
    request.refresh_from_db()
    return request


def quote_data(*, freight_request, user, base=Decimal("5000")):
    return FreightQuoteData(
        freight_request=freight_request,
        created_by=user,
        charges=(
            ChargeData(
                charge_type=FreightQuoteChargeType.BASE_FREIGHT,
                unit_amount=base,
            ),
        ),
        valid_until="2026-12-31",
    )


@pytest.mark.django_db
def test_quote_total_calculation():
    assert charge_line_total(quantity=Decimal("2"), unit_amount=Decimal("100")) == Decimal("200.00")


@pytest.mark.django_db(transaction=True)
def test_create_quote_and_request_quoting(organization, django_user_model):
    user = django_user_model.objects.create_user(username="seller", password="pass")
    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=user, customer=customer)
    quote = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    request.refresh_from_db()
    assert quote.reference_code.startswith("FQ-")
    assert quote.total_amount == Decimal("5000.00")
    assert request.status == FreightRequestStatus.QUOTING.value
    assert quote.premises_snapshot["request_reference"] == request.reference_code


@pytest.mark.django_db(transaction=True)
def test_quote_charges_discount_and_negative_total_blocked(organization, django_user_model):
    user = django_user_model.objects.create_user(username="seller2", password="pass")
    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=user, customer=customer)
    with pytest.raises(ValidationError):
        create_freight_quote(
            data=FreightQuoteData(
                freight_request=request,
                created_by=user,
                charges=(
                    ChargeData(
                        charge_type=FreightQuoteChargeType.BASE_FREIGHT,
                        unit_amount=Decimal("100"),
                    ),
                    ChargeData(
                        charge_type=FreightQuoteChargeType.DISCOUNT,
                        unit_amount=Decimal("200"),
                        is_discount=True,
                    ),
                ),
            ),
            actor=user,
        )


@pytest.mark.django_db(transaction=True)
def test_quote_state_machine_flow(organization, django_user_model):
    user = django_user_model.objects.create_user(username="mgr", password="pass")
    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=user, customer=customer)
    quote = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    send_freight_quote(quote, actor=user)
    quote.refresh_from_db()
    assert quote.status == FreightQuoteStatus.SENT.value
    assert AuditLog.objects.filter(action="freight_quote_sent", target_id=str(quote.id)).exists()


@pytest.mark.django_db
def test_invalid_quote_transition():
    assert not can_transition_quote(
        current=FreightQuoteStatus.CANCELLED, target=FreightQuoteStatus.DRAFT
    )


@pytest.mark.django_db(transaction=True)
def test_revise_quote_preserves_history(organization, django_user_model):
    user = django_user_model.objects.create_user(username="rev", password="pass")
    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=user, customer=customer)
    original = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    submit_freight_quote_for_review(original, actor=user)
    approve_freight_quote(original, actor=user)
    revised = revise_freight_quote(
        original,
        data=quote_data(freight_request=request, user=user, base=Decimal("6000")),
        actor=user,
    )
    original.refresh_from_db()
    assert original.status == FreightQuoteStatus.SUPERSEDED.value
    assert revised.version == 2
    assert revised.total_amount == Decimal("6000.00")


@pytest.mark.django_db(transaction=True)
def test_rbac_margin_and_scope(organization, other_organization, django_user_model, rbac_ready):
    owner = django_user_model.objects.create_user(username="sales", password="pass")
    outsider = django_user_model.objects.create_user(username="out", password="pass")
    grant(owner, organization, RoleCode.SALESPERSON, AccessScope.OWN)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN, AccessScope.COMPANY)

    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=owner, customer=customer)
    quote = create_freight_quote(data=quote_data(freight_request=request, user=owner), actor=owner)
    quote.owner = owner
    quote.estimated_cost = Decimal("3000")
    quote.save(update_fields=["owner", "estimated_cost"])

    assert quote in scoped_freight_quote_queryset(owner, PermissionCode.FREIGHT_QUOTES_VIEW)
    assert quote not in scoped_freight_quote_queryset(outsider, PermissionCode.FREIGHT_QUOTES_VIEW)
    assert not user_has_backoffice_permission(owner, PermissionCode.FREIGHT_QUOTES_VIEW_MARGIN)


@pytest.mark.django_db(transaction=True)
def test_backoffice_quote_http_margin_leak(client, django_user_model, organization, rbac_ready):
    admin = django_user_model.objects.create_user(username="q-admin", password="safe-pass-123")
    sales = django_user_model.objects.create_user(username="q-sales", password="safe-pass-123")
    grant(admin, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)
    grant(sales, organization, RoleCode.SALESPERSON, AccessScope.COMPANY)

    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=admin, customer=customer)
    quote = create_freight_quote(
        data=FreightQuoteData(
            freight_request=request,
            created_by=admin,
            estimated_cost=Decimal("2500"),
            charges=(
                ChargeData(
                    charge_type=FreightQuoteChargeType.BASE_FREIGHT,
                    unit_amount=Decimal("5000"),
                ),
            ),
        ),
        actor=admin,
    )

    client.force_login(sales)
    response = client.get(
        reverse("backoffice:freight_quote_detail", args=[quote.id]),
        HTTP_HOST="localhost",
    )
    assert response.status_code == 200
    assert b"estimated_cost" not in response.content.lower()
    assert b"Margem" not in response.content

    client.force_login(admin)
    response = client.get(
        reverse("backoffice:freight_quote_detail", args=[quote.id]),
        HTTP_HOST="localhost",
    )
    assert b"Margem" in response.content or b"margem" in response.content.lower()

    response = client.post(
        reverse("backoffice:freight_quote_review", args=[quote.id]),
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    quote.refresh_from_db()
    assert quote.status == FreightQuoteStatus.UNDER_REVIEW.value

    fake_id = uuid.uuid4()
    assert (
        client.get(
            reverse("backoffice:freight_quote_detail", args=[fake_id]),
            HTTP_HOST="localhost",
        ).status_code
        == 404
    )
