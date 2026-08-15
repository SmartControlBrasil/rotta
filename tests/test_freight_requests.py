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
from src.freights.application.services import (
    CargoData,
    FreightRequestData,
    StopData,
    assign_freight_request_owner,
    cancel_freight_request,
    change_freight_request_status,
    create_freight_request,
    submit_freight_request,
    update_freight_request,
)
from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightCargoType,
    FreightRequestStatus,
    FreightStopType,
)
from src.freights.domain.state_machine import can_transition
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightRequestCargo,
    FreightRequestStop,
)
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.interfaces.backoffice.authorization import (
    scoped_freight_request_queryset,
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


def make_customer(organization, *, legal_name="Cliente Teste"):
    return register_customer(
        data=CustomerData(
            organization=organization,
            customer_type=CustomerType.COMPANY,
            legal_name=legal_name,
            document_number="11.222.333/0001-81",
            email=f"{legal_name.replace(' ', '').lower()}@example.com",
        )
    )


def dry_payload(*, organization, customer, created_by):
    return FreightRequestData(
        organization=organization,
        customer=customer,
        created_by=created_by,
        stops=(
            StopData(
                stop_type=FreightStopType.PICKUP,
                city="São Paulo",
                state="SP",
                scheduled_date="2026-08-20",
            ),
            StopData(
                stop_type=FreightStopType.DELIVERY,
                sequence=2,
                city="Campinas",
                state="SP",
            ),
        ),
        cargo=CargoData(
            description="Caixas de produtos secos",
            cargo_profile=FreightCargoProfile.DRY_CARGO,
            weight_kg=Decimal("1200.500"),
        ),
    )


def refrigerated_payload(*, organization, customer, created_by):
    return FreightRequestData(
        organization=organization,
        customer=customer,
        created_by=created_by,
        stops=(
            StopData(stop_type=FreightStopType.PICKUP, sequence=1, city="Curitiba", state="PR"),
            StopData(
                stop_type=FreightStopType.DELIVERY,
                sequence=2,
                city="Florianópolis",
                state="SC",
            ),
        ),
        cargo=CargoData(
            description="Laticínios refrigerados",
            cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
            weight_kg=Decimal("800"),
            temperature_min_c=Decimal("2"),
            temperature_max_c=Decimal("8"),
            target_temperature_c=Decimal("4"),
        ),
    )


@pytest.mark.django_db
def test_freight_request_models_and_stop_ordering(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops", password="pass")
    customer = make_customer(organization)
    request = create_freight_request(
        data=dry_payload(organization=organization, customer=customer, created_by=user)
    )
    assert request.reference_code.startswith("FR-")
    stops = list(request.stops.order_by("sequence"))
    assert len(stops) == 2
    assert stops[0].stop_type == FreightStopType.PICKUP.value
    assert stops[1].stop_type == FreightStopType.DELIVERY.value
    assert request.pickup_stop.city == "São Paulo"
    assert request.delivery_stop.city == "Campinas"


@pytest.mark.django_db
def test_cargo_temperature_validation(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops2", password="pass")
    customer = make_customer(organization)
    request = create_freight_request(
        data=refrigerated_payload(organization=organization, customer=customer, created_by=user)
    )
    cargo = request.cargo
    assert cargo.temperature_min_c == Decimal("2")

    invalid = FreightRequestCargo(
        freight_request=request,
        cargo_profile=FreightCargoProfile.DRY_CARGO.value,
        temperature_min_c=Decimal("1"),
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()

    invalid_ref = FreightRequestCargo(
        freight_request=request,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value,
        temperature_min_c=Decimal("8"),
        temperature_max_c=Decimal("2"),
    )
    with pytest.raises(ValidationError):
        invalid_ref.full_clean()

    invalid_setpoint = FreightRequestCargo(
        freight_request=request,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value,
        temperature_min_c=Decimal("2"),
        temperature_max_c=Decimal("8"),
        target_temperature_c=Decimal("12"),
    )
    with pytest.raises(ValidationError):
        invalid_setpoint.full_clean()


@pytest.mark.django_db
def test_state_machine_transitions():
    assert can_transition(current=FreightRequestStatus.DRAFT, target=FreightRequestStatus.SUBMITTED)
    assert can_transition(
        current=FreightRequestStatus.SUBMITTED, target=FreightRequestStatus.UNDER_REVIEW
    )
    assert not can_transition(
        current=FreightRequestStatus.CANCELLED, target=FreightRequestStatus.DRAFT
    )
    assert not can_transition(
        current=FreightRequestStatus.DRAFT, target=FreightRequestStatus.UNDER_REVIEW
    )


@pytest.mark.django_db(transaction=True)
def test_submit_cancel_and_audit(organization, django_user_model):
    actor = django_user_model.objects.create_user(username="actor", password="pass")
    customer = make_customer(organization)
    request = create_freight_request(
        data=dry_payload(organization=organization, customer=customer, created_by=actor),
        actor=actor,
    )
    assert AuditLog.objects.filter(
        action="freight_request_created", target_id=str(request.id)
    ).exists()

    submit_freight_request(request, actor=actor)
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.SUBMITTED.value
    assert request.submitted_at is not None
    assert AuditLog.objects.filter(
        action="freight_request_submitted", target_id=str(request.id)
    ).exists()

    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=actor)
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.UNDER_REVIEW.value

    cancel_freight_request(request, reason="Cliente desistiu", actor=actor)
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.CANCELLED.value
    assert request.cancellation_reason == "Cliente desistiu"
    assert AuditLog.objects.filter(
        action="freight_request_cancelled", target_id=str(request.id)
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_submit_requires_integrity(organization, django_user_model):
    actor = django_user_model.objects.create_user(username="actor2", password="pass")
    customer = make_customer(organization)
    request = create_freight_request(
        data=FreightRequestData(
            organization=organization,
            customer=customer,
            created_by=actor,
            cargo=CargoData(cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO),
        ),
        actor=actor,
    )
    with pytest.raises(ValidationError):
        submit_freight_request(request, actor=actor)


@pytest.mark.django_db(transaction=True)
def test_refrigerated_submit_validation_cases(organization, django_user_model):
    actor = django_user_model.objects.create_user(username="actor3", password="pass")
    customer = make_customer(organization)

    valid = create_freight_request(
        data=refrigerated_payload(organization=organization, customer=customer, created_by=actor)
    )
    submit_freight_request(valid, actor=actor)

    draft = create_freight_request(
        data=FreightRequestData(
            organization=organization,
            customer=customer,
            created_by=actor,
            stops=(
                StopData(stop_type=FreightStopType.PICKUP, sequence=1, city="A", state="SP"),
                StopData(stop_type=FreightStopType.DELIVERY, sequence=2, city="B", state="RJ"),
            ),
            cargo=CargoData(
                cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
                weight_kg=Decimal("10"),
            ),
        )
    )
    with pytest.raises(ValidationError):
        submit_freight_request(draft, actor=actor)


@pytest.mark.django_db(transaction=True)
def test_rbac_and_scoping(organization, other_organization, django_user_model, rbac_ready):
    owner = django_user_model.objects.create_user(username="owner", password="pass")
    outsider = django_user_model.objects.create_user(username="outsider", password="pass")
    grant(owner, organization, RoleCode.SALESPERSON, AccessScope.OWN)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)

    customer = make_customer(organization)
    owned = create_freight_request(
        data=dry_payload(organization=organization, customer=customer, created_by=owner),
        actor=owner,
    )
    owned.owner = owner
    owned.save(update_fields=["owner"])

    other_customer = make_customer(other_organization, legal_name="Cliente Outro")
    hidden = create_freight_request(
        data=dry_payload(
            organization=other_organization,
            customer=other_customer,
            created_by=outsider,
        ),
        actor=outsider,
    )

    scoped = scoped_freight_request_queryset(owner, PermissionCode.FREIGHT_REQUESTS_VIEW)
    assert owned in scoped
    assert hidden not in scoped
    assert user_has_backoffice_permission(owner, PermissionCode.FREIGHT_REQUESTS_CREATE)
    assert not user_has_backoffice_permission(owner, PermissionCode.FREIGHT_REQUESTS_CHANGE_STATUS)


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_customer_rejected(organization, other_organization, django_user_model):
    actor = django_user_model.objects.create_user(username="actor4", password="pass")
    foreign_customer = make_customer(other_organization, legal_name="Cliente Fora")
    with pytest.raises(ValidationError):
        create_freight_request(
            data=dry_payload(
                organization=organization,
                customer=foreign_customer,
                created_by=actor,
            )
        )


@pytest.mark.django_db(transaction=True)
def test_assign_owner_audit(organization, django_user_model):
    actor = django_user_model.objects.create_user(username="actor5", password="pass")
    new_owner = django_user_model.objects.create_user(username="newowner", password="pass")
    customer = make_customer(organization)
    request = create_freight_request(
        data=dry_payload(organization=organization, customer=customer, created_by=actor),
        actor=actor,
    )
    assign_freight_request_owner(request, owner=new_owner, actor=actor)
    request.refresh_from_db()
    assert request.owner == new_owner
    assert AuditLog.objects.filter(
        action="freight_request_owner_changed", target_id=str(request.id)
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_backoffice_freight_request_http(client, django_user_model, organization, rbac_ready):
    admin = django_user_model.objects.create_user(username="fr-admin", password="safe-pass-123")
    viewer = django_user_model.objects.create_user(username="fr-viewer", password="safe-pass-123")
    outsider = django_user_model.objects.create_user(
        username="fr-outsider", password="safe-pass-123"
    )
    grant(admin, organization, RoleCode.COMPANY_ADMIN, AccessScope.ALL)
    grant(viewer, organization, RoleCode.VIEWER, AccessScope.COMPANY)

    customer = make_customer(organization)

    response = client.get(reverse("backoffice:freight_requests"))
    assert response.status_code == 302

    client.force_login(viewer)
    assert (
        client.get(reverse("backoffice:freight_requests"), HTTP_HOST="localhost").status_code == 403
    )

    client.force_login(admin)
    assert (
        client.get(reverse("backoffice:freight_requests"), HTTP_HOST="localhost").status_code == 200
    )

    response = client.post(
        reverse("backoffice:freight_request_create"),
        {
            "customer": str(customer.id),
            "priority": "NORMAL",
            "pickup_city": "São Paulo",
            "pickup_state": "SP",
            "pickup_date": "2026-08-20",
            "delivery_city": "Rio de Janeiro",
            "delivery_state": "RJ",
            "cargo_description": "Carga teste",
            "cargo_type": FreightCargoType.GENERAL_CARGO.value,
            "cargo_profile": FreightCargoProfile.DRY_CARGO.value,
            "weight_kg": "1500",
        },
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    request = FreightRequest.objects.get(cargo__description="Carga teste")

    assert (
        client.get(
            reverse("backoffice:freight_request_detail", args=[request.id]),
            HTTP_HOST="localhost",
        ).status_code
        == 200
    )

    response = client.post(
        reverse("backoffice:freight_request_submit", args=[request.id]),
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.SUBMITTED.value

    response = client.post(
        reverse("backoffice:freight_request_cancel", args=[request.id]),
        {"cancellation_reason": "Teste"},
        HTTP_HOST="localhost",
    )
    assert response.status_code == 302
    request.refresh_from_db()
    assert request.status == FreightRequestStatus.CANCELLED.value

    fake_id = uuid.uuid4()
    assert (
        client.get(
            reverse("backoffice:freight_request_detail", args=[fake_id]),
            HTTP_HOST="localhost",
        ).status_code
        == 404
    )

    client.force_login(outsider)
    assert (
        client.get(
            reverse("backoffice:freight_request_detail", args=[request.id]),
            HTTP_HOST="localhost",
        ).status_code
        == 403
    )

    client.force_login(admin)
    get_response = client.get(
        reverse("backoffice:freight_request_submit", args=[request.id]),
        HTTP_HOST="localhost",
    )
    assert get_response.status_code == 405


@pytest.mark.django_db(transaction=True)
def test_update_draft_only(organization, django_user_model):
    actor = django_user_model.objects.create_user(username="actor6", password="pass")
    customer = make_customer(organization)
    request = create_freight_request(
        data=dry_payload(organization=organization, customer=customer, created_by=actor),
        actor=actor,
    )
    update_freight_request(
        request,
        actor=actor,
        instructions="Agendar com antecedência",
    )
    request.refresh_from_db()
    assert request.instructions == "Agendar com antecedência"

    submit_freight_request(request, actor=actor)
    with pytest.raises(ValidationError):
        update_freight_request(request, actor=actor, instructions="Não deve")


@pytest.mark.django_db
def test_stop_window_validation(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ops3", password="pass")
    customer = make_customer(organization)
    stop = FreightRequestStop(
        freight_request=FreightRequest(
            organization=organization,
            customer=customer,
            created_by=user,
            reference_code="FR-TMP",
        ),
        stop_type=FreightStopType.PICKUP.value,
        window_start="18:00",
        window_end="08:00",
    )
    with pytest.raises(ValidationError):
        stop.full_clean()
