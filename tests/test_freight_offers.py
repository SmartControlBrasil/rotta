from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus
from src.carriers.infrastructure.django.models import CarrierProfile
from src.compliance.application.evaluation import evaluate_entity_compliance
from src.compliance.domain.enums import ComplianceStatus, EntityType
from src.customers.application.services import CustomerData, register_customer
from src.customers.domain.enums import CustomerType
from src.drivers.domain.enums import DriverStatus
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.eligibility import is_entity_eligible_for_offer
from src.freights.application.marketplace_queries import published_offer_queryset_for_actor
from src.freights.application.offer_services import (
    FreightOfferData,
    add_freight_offer_target,
    cancel_freight_offer,
    create_freight_offer,
    mark_freight_offer_ready,
    pause_freight_offer,
    publish_freight_offer,
    resume_freight_offer,
)
from src.freights.application.quote_services import (
    ChargeData,
    FreightQuoteData,
    approve_freight_quote,
    create_freight_quote,
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
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.domain.offer_state_machine import can_transition_offer
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.interfaces.backoffice.authorization import (
    scoped_freight_offer_queryset,
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
        type=OrganizationType.TRANSPORT_COMPANY,
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


def submitted_request(*, organization, user, customer, cargo_profile=FreightCargoProfile.DRY_CARGO):
    cargo_kwargs = {
        "description": "Carga",
        "weight_kg": Decimal("1000"),
        "cargo_profile": cargo_profile,
    }
    if cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO:
        cargo_kwargs.update(
            {
                "temperature_min_c": Decimal("-5"),
                "temperature_max_c": Decimal("5"),
                "target_temperature_c": Decimal("0"),
            }
        )
    request = create_freight_request(
        data=FreightRequestData(
            organization=organization,
            customer=customer,
            created_by=user,
            stops=(
                StopData(stop_type=FreightStopType.PICKUP, sequence=1, city="SP", state="SP"),
                StopData(stop_type=FreightStopType.DELIVERY, sequence=2, city="RJ", state="RJ"),
            ),
            cargo=CargoData(**cargo_kwargs),
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


def ready_request_with_quote(*, organization, user, customer, offer_base=Decimal("5000")):
    request = submitted_request(organization=organization, user=user, customer=customer)
    quote = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.READY_TO_PUBLISH.value
    return request, quote


def make_offer(
    *,
    request,
    quote,
    user,
    amount=Decimal("3500"),
    audience=FreightOfferAudience.CARRIERS,
):
    expires_at = timezone.now() + timedelta(days=7)
    return create_freight_offer(
        data=FreightOfferData(
            freight_request=request,
            freight_quote=quote,
            created_by=user,
            offer_amount=amount,
            audience=audience,
            expires_at=expires_at,
        ),
        actor=user,
    )


def make_carrier(*, tenant, email="carrier@example.com", **kwargs):
    carrier_org = Organization.objects.create(
        name=f"Carrier Org {email}",
        type=OrganizationType.PARTNER,
    )
    defaults = {
        "status": CarrierStatus.ACTIVE.value,
        "cargo_profile": CarrierCargoProfile.DRY_CARGO.value,
    }
    defaults.update(kwargs)
    return CarrierProfile.objects.create(
        organization=carrier_org,
        tenant=tenant,
        email=email,
        **defaults,
    )


@pytest.mark.django_db(transaction=True)
def test_offer_model_reference_amount_snapshot(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops1", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    offer = make_offer(request=request, quote=quote, user=user, amount=Decimal("3200.50"))
    assert offer.reference_code.startswith("FO-")
    assert offer.offer_amount == Decimal("3200.50")
    assert offer.freight_quote_id == quote.id
    assert offer.premises_snapshot["request_reference"] == request.reference_code
    assert offer.spread_amount == Decimal("1799.50")


@pytest.mark.django_db(transaction=True)
def test_offer_gate_requires_ready_to_publish(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops2", password="pass")
    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=user, customer=customer)
    quote = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    with pytest.raises(ValidationError):
        make_offer(request=request, quote=quote, user=user)


@pytest.mark.django_db(transaction=True)
def test_quote_approve_moves_request_to_ready_to_publish(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops3", password="pass")
    customer = make_customer(organization)
    request = submitted_request(organization=organization, user=user, customer=customer)
    quote = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.READY_TO_PUBLISH.value


@pytest.mark.django_db(transaction=True)
def test_offer_state_machine_flow(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops4", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    offer = make_offer(request=request, quote=quote, user=user)
    assert offer.status == FreightOfferStatus.DRAFT.value

    offer = mark_freight_offer_ready(offer, actor=user)
    assert offer.status == FreightOfferStatus.READY.value

    offer = publish_freight_offer(offer, actor=user)
    assert offer.status == FreightOfferStatus.PUBLISHED.value
    assert offer.published_at is not None

    offer = pause_freight_offer(offer, actor=user)
    assert offer.status == FreightOfferStatus.PAUSED.value

    offer = resume_freight_offer(offer, actor=user)
    assert offer.status == FreightOfferStatus.PUBLISHED.value


@pytest.mark.django_db(transaction=True)
def test_offer_invalid_transitions(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops5", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    offer = make_offer(request=request, quote=quote, user=user)
    with pytest.raises(ValidationError):
        publish_freight_offer(offer, actor=user)
    assert not can_transition_offer(
        current=FreightOfferStatus.DRAFT,
        target=FreightOfferStatus.PUBLISHED,
    )


@pytest.mark.django_db(transaction=True)
def test_offer_cancel_and_negative_amount(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops6", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    with pytest.raises(ValidationError):
        create_freight_offer(
            data=FreightOfferData(
                freight_request=request,
                freight_quote=quote,
                created_by=user,
                offer_amount=Decimal("-1"),
            ),
            actor=user,
        )
    offer = make_offer(request=request, quote=quote, user=user)
    offer = mark_freight_offer_ready(offer, actor=user)
    offer = cancel_freight_offer(offer, reason="Teste", actor=user)
    assert offer.status == FreightOfferStatus.CANCELLED.value


@pytest.mark.django_db(transaction=True)
def test_refrigerated_snapshot_preserves_thermal_requirements(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops7", password="pass")
    customer = make_customer(organization)
    request = submitted_request(
        organization=organization,
        user=user,
        customer=customer,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
    )
    quote = create_freight_quote(data=quote_data(freight_request=request, user=user), actor=user)
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    request.refresh_from_db()
    offer = make_offer(request=request, quote=quote, user=user)
    assert offer.premises_snapshot["cargo_profile"] == FreightCargoProfile.REFRIGERATED_CARGO.value
    assert offer.premises_snapshot["temperature_min_c"] == "-5.00"
    assert offer.premises_snapshot["target_temperature_c"] == "0.00"


@pytest.mark.django_db(transaction=True)
def test_eligibility_compliance_carrier_and_driver(organization):
    carrier_ok = make_carrier(
        tenant=organization,
        email="carrier-ok@example.com",
        cargo_profile=CarrierCargoProfile.BOTH.value,
    )
    carrier_bad = make_carrier(
        tenant=organization,
        email="carrier-bad@example.com",
        status=CarrierStatus.BLOCKED.value,
    )
    driver_ok = Driver.objects.create(
        organization=organization,
        full_name="Driver OK",
        status=DriverStatus.ACTIVE.value,
    )
    driver_bad = Driver.objects.create(
        organization=organization,
        full_name="Driver Bad",
        status=DriverStatus.BLOCKED.value,
    )
    offer = type(
        "OfferStub",
        (),
        {
            "organization_id": organization.id,
            "premises_snapshot": {"cargo_profile": FreightCargoProfile.DRY_CARGO.value},
        },
    )()
    assert not is_entity_eligible_for_offer(offer=offer, carrier=carrier_bad)
    assert not is_entity_eligible_for_offer(offer=offer, driver=driver_bad)
    if (
        evaluate_entity_compliance(
            entity_type=EntityType.DRIVER, documents=driver_ok.documents.all()
        ).status
        == ComplianceStatus.COMPLIANT
    ):
        assert is_entity_eligible_for_offer(offer=offer, driver=driver_ok)
    assert is_entity_eligible_for_offer(offer=offer, carrier=carrier_ok)


@pytest.mark.django_db(transaction=True)
def test_private_targets_and_audience(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops8", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    carrier = make_carrier(
        tenant=organization,
        email="target-carrier@example.com",
        cargo_profile=CarrierCargoProfile.BOTH.value,
    )
    offer = make_offer(
        request=request,
        quote=quote,
        user=user,
        audience=FreightOfferAudience.PRIVATE,
    )
    add_freight_offer_target(offer, carrier=carrier, actor=user)
    assert offer.targets.filter(carrier=carrier).exists()
    offer = mark_freight_offer_ready(offer, actor=user)
    offer = publish_freight_offer(offer, actor=user)
    assert offer.audience == FreightOfferAudience.PRIVATE.value


@pytest.mark.django_db(transaction=True)
def test_marketplace_query_filters_visibility(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops9", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    carrier = make_carrier(
        tenant=organization,
        email="market-carrier@example.com",
        cargo_profile=CarrierCargoProfile.BOTH.value,
    )
    published = make_offer(
        request=request,
        quote=quote,
        user=user,
        audience=FreightOfferAudience.CARRIERS,
    )
    published = mark_freight_offer_ready(published, actor=user)
    published = publish_freight_offer(published, actor=user)

    draft = make_offer(
        request=request,
        quote=quote,
        user=user,
        amount=Decimal("3000"),
        audience=FreightOfferAudience.CARRIERS,
    )

    paused = make_offer(
        request=request,
        quote=quote,
        user=user,
        amount=Decimal("3100"),
        audience=FreightOfferAudience.CARRIERS,
    )
    paused = mark_freight_offer_ready(paused, actor=user)
    paused = publish_freight_offer(paused, actor=user)
    paused = pause_freight_offer(paused, actor=user)

    private_no_targets = make_offer(
        request=request,
        quote=quote,
        user=user,
        amount=Decimal("2900"),
        audience=FreightOfferAudience.PRIVATE,
    )
    private_no_targets = mark_freight_offer_ready(private_no_targets, actor=user)
    with pytest.raises(ValidationError):
        publish_freight_offer(private_no_targets, actor=user)

    visible = published_offer_queryset_for_actor(
        organization_id=organization.id,
        carrier=carrier,
    )
    assert published in visible
    assert draft not in visible
    assert paused not in visible


@pytest.mark.django_db(transaction=True)
def test_rbac_and_scope(organization, other_organization, django_user_model, rbac_ready):
    owner = django_user_model.objects.create_user(username="dispatcher", password="pass")
    outsider = django_user_model.objects.create_user(username="out-offer", password="pass")
    grant(owner, organization, RoleCode.DISPATCHER, AccessScope.COMPANY)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN, AccessScope.COMPANY)

    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=owner, customer=customer
    )
    offer = make_offer(request=request, quote=quote, user=owner)
    offer.owner = owner
    offer.save(update_fields=["owner"])

    assert offer in scoped_freight_offer_queryset(owner, PermissionCode.FREIGHT_OFFERS_VIEW)
    assert offer not in scoped_freight_offer_queryset(outsider, PermissionCode.FREIGHT_OFFERS_VIEW)
    assert user_has_backoffice_permission(owner, PermissionCode.FREIGHT_OFFERS_PUBLISH)
    assert not user_has_backoffice_permission(owner, PermissionCode.FREIGHT_OFFERS_VIEW_MARGIN)


@pytest.mark.django_db(transaction=True)
def test_commercial_view_without_margin_leak(client, django_user_model, organization, rbac_ready):
    admin = django_user_model.objects.create_user(username="offer-admin", password="safe-pass-123")
    commercial = django_user_model.objects.create_user(
        username="offer-commercial", password="safe-pass-123"
    )
    grant(admin, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)
    grant(commercial, organization, RoleCode.COMMERCIAL_MANAGER, AccessScope.COMPANY)

    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=admin, customer=customer
    )
    offer = make_offer(request=request, quote=quote, user=admin, amount=Decimal("3000"))

    client.force_login(commercial)
    response = client.get(
        reverse("backoffice:freight_offer_detail", args=[offer.id]),
        HTTP_HOST="localhost",
    )
    assert response.status_code == 200
    content = response.content.decode().lower()
    assert "spread" not in content
    assert "preço cliente" not in content

    client.force_login(admin)
    response = client.get(
        reverse("backoffice:freight_offer_detail", args=[offer.id]),
        HTTP_HOST="localhost",
    )
    assert b"Spread" in response.content or b"spread" in response.content.lower()


@pytest.mark.django_db(transaction=True)
def test_salesperson_cannot_publish(client, django_user_model, organization, rbac_ready):
    sales = django_user_model.objects.create_user(username="offer-sales", password="safe-pass-123")
    grant(sales, organization, RoleCode.SALESPERSON, AccessScope.COMPANY)
    assert not user_has_backoffice_permission(sales, PermissionCode.FREIGHT_OFFERS_PUBLISH)


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_offer_creation_blocked(organization, other_organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops10", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization, user=user, customer=customer
    )
    other_customer = make_customer(other_organization)
    other_request = submitted_request(
        organization=other_organization, user=user, customer=other_customer
    )
    with pytest.raises(ValidationError):
        create_freight_offer(
            data=FreightOfferData(
                freight_request=other_request,
                freight_quote=quote,
                created_by=user,
                offer_amount=Decimal("1000"),
            ),
            actor=user,
        )
