from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from src.drivers.application.route_compatibility import evaluate_route_intent_compatibility
from src.drivers.application.route_intent_services import (
    DriverRouteIntentData,
    activate_driver_route_intent,
    apply_route_intent_expiration_if_needed,
    cancel_driver_route_intent,
    create_driver_route_intent,
    get_active_route_intents_for_driver,
)
from src.drivers.domain.route_intent_enums import (
    DriverRouteIntentSource,
    DriverRouteIntentStatus,
    DriverRouteIntentType,
    RouteIntentCargoPreference,
    RouteIntentCompatibilityLevel,
)
from src.drivers.infrastructure.django.models import Driver, DriverRouteIntent
from src.freights.application.offer_services import (
    FreightOfferData,
    create_freight_offer,
    mark_freight_offer_ready,
    publish_freight_offer,
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
from src.freights.domain.enums import FreightCargoProfile, FreightRequestStatus, FreightStopType
from src.freights.domain.offer_enums import FreightOfferAudience
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.interfaces.backoffice.authorization import (
    scoped_driver_route_intent_queryset,
    user_has_backoffice_permission,
)
from src.vehicles.application.services import VehicleData, assign_driver_to_vehicle, register_vehicle
from src.vehicles.domain.enums import VehicleCargoProfile, VehicleOperationalStatus, VehicleStatus, VehicleType


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Rotta Route Intent",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization():
    return Organization.objects.create(
        name="Outra Route Intent",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization)
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


def active_driver(*, organization, name="Motorista Rota"):
    from src.drivers.domain.enums import DriverAvailabilityStatus, DriverStatus

    return Driver.objects.create(
        organization=organization,
        full_name=name,
        status=DriverStatus.ACTIVE.value,
        availability_status=DriverAvailabilityStatus.AVAILABLE.value,
    )


def intent_data(*, organization, driver, vehicle=None, **kwargs):
    now = timezone.now()
    defaults = {
        "organization": organization,
        "driver": driver,
        "vehicle": vehicle,
        "intent_type": DriverRouteIntentType.RETURN_LOAD,
        "origin_city": "Curitiba",
        "origin_state": "PR",
        "destination_city": "São Paulo",
        "destination_state": "SP",
        "available_from": now + timedelta(hours=1),
        "available_until": now + timedelta(days=2),
        "source": DriverRouteIntentSource.BACKOFFICE,
    }
    defaults.update(kwargs)
    return DriverRouteIntentData(**defaults)


def published_offer(
    *,
    organization,
    user,
    pickup,
    delivery,
    customer=None,
    cargo_profile=FreightCargoProfile.DRY_CARGO,
):
    from src.customers.application.services import CustomerData, register_customer
    from src.customers.domain.enums import CustomerType

    if customer is None:
        customer = register_customer(
            data=CustomerData(
                organization=organization,
                customer_type=CustomerType.COMPANY,
                legal_name="Cliente Rota",
                document_number="11.222.333/0001-81",
                email="rota@example.com",
            )
        )
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
                StopData(
                    stop_type=FreightStopType.PICKUP,
                    sequence=1,
                    city=pickup[0],
                    state=pickup[1],
                ),
                StopData(
                    stop_type=FreightStopType.DELIVERY,
                    sequence=2,
                    city=delivery[0],
                    state=delivery[1],
                ),
            ),
            cargo=CargoData(**cargo_kwargs),
        ),
        actor=user,
    )
    submit_freight_request(request, actor=user)
    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=user)
    quote = create_freight_quote(
        data=FreightQuoteData(
            freight_request=request,
            created_by=user,
            charges=(ChargeData(charge_type=FreightQuoteChargeType.BASE_FREIGHT, unit_amount=Decimal("5000")),),
            valid_until="2026-12-31",
        ),
        actor=user,
    )
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    offer = create_freight_offer(
        data=FreightOfferData(
            freight_request=request,
            freight_quote=quote,
            created_by=user,
            offer_amount=Decimal("3500"),
            audience=FreightOfferAudience.DRIVERS,
            expires_at=timezone.now() + timedelta(days=7),
        ),
        actor=user,
    )
    offer = mark_freight_offer_ready(offer, actor=user)
    return publish_freight_offer(offer, actor=user)


@pytest.mark.django_db(transaction=True)
def test_create_valid_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="route-1", password="pass")
    driver = active_driver(organization=organization)
    intent = create_driver_route_intent(
        data=intent_data(organization=organization, driver=driver),
        actor=user,
    )
    assert intent.status == DriverRouteIntentStatus.DRAFT.value
    assert intent.origin_state == "PR"
    assert intent.destination_state == "SP"


@pytest.mark.django_db(transaction=True)
def test_invalid_availability_window(organization):
    driver = active_driver(organization=organization)
    now = timezone.now()
    with pytest.raises(ValidationError):
        create_driver_route_intent(
            data=intent_data(
                organization=organization,
                driver=driver,
                available_from=now + timedelta(days=2),
                available_until=now + timedelta(days=1),
            )
        )


@pytest.mark.django_db(transaction=True)
def test_activate_and_cancel_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="route-2", password="pass")
    driver = active_driver(organization=organization)
    intent = create_driver_route_intent(
        data=intent_data(organization=organization, driver=driver),
        actor=user,
    )
    intent = activate_driver_route_intent(intent, actor=user)
    assert intent.status == DriverRouteIntentStatus.ACTIVE.value
    assert get_active_route_intents_for_driver(driver)
    intent = cancel_driver_route_intent(intent, actor=user, reason="Mudou rota")
    assert intent.status == DriverRouteIntentStatus.CANCELLED.value


@pytest.mark.django_db(transaction=True)
def test_lazy_expiration(organization, django_user_model):
    user = django_user_model.objects.create_user(username="route-3", password="pass")
    driver = active_driver(organization=organization)
    now = timezone.now()
    intent = create_driver_route_intent(
        data=intent_data(
            organization=organization,
            driver=driver,
            available_from=now - timedelta(days=2),
            available_until=now + timedelta(days=1),
        ),
        actor=user,
    )
    intent = activate_driver_route_intent(intent, actor=user)
    DriverRouteIntent.objects.filter(pk=intent.pk).update(
        available_until=now - timedelta(hours=1)
    )
    intent.refresh_from_db()
    expired = apply_route_intent_expiration_if_needed(intent, actor=user)
    assert expired.status == DriverRouteIntentStatus.EXPIRED.value


@pytest.mark.django_db(transaction=True)
def test_vehicle_assignment_required(organization):
    driver = active_driver(organization=organization)
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate="ROT1A11",
            vehicle_type=VehicleType.VAN,
            status=VehicleStatus.ACTIVE,
            operational_status=VehicleOperationalStatus.AVAILABLE,
        )
    )
    with pytest.raises(ValidationError):
        create_driver_route_intent(
            data=intent_data(organization=organization, driver=driver, vehicle=vehicle)
        )


@pytest.mark.django_db(transaction=True)
def test_vehicle_assignment_valid(organization):
    driver = active_driver(organization=organization)
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate="ROT2B22",
            vehicle_type=VehicleType.VAN,
            status=VehicleStatus.ACTIVE,
            operational_status=VehicleOperationalStatus.AVAILABLE,
        )
    )
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    intent = create_driver_route_intent(
        data=intent_data(organization=organization, driver=driver, vehicle=vehicle)
    )
    assert intent.vehicle_id == vehicle.id


@pytest.mark.django_db(transaction=True)
def test_refrigerated_preference_requires_capable_vehicle(organization):
    driver = active_driver(organization=organization)
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate="DRY3C33",
            vehicle_type=VehicleType.VAN,
            cargo_profile=VehicleCargoProfile.DRY_CARGO,
            status=VehicleStatus.ACTIVE,
        )
    )
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    with pytest.raises(ValidationError):
        create_driver_route_intent(
            data=intent_data(
                organization=organization,
                driver=driver,
                vehicle=vehicle,
                cargo_preference=RouteIntentCargoPreference.REFRIGERATED_CARGO,
            )
        )


@pytest.mark.django_db(transaction=True)
def test_intent_types_share_same_entity(organization):
    driver = active_driver(organization=organization)
    return_intent = create_driver_route_intent(
        data=intent_data(
            organization=organization,
            driver=driver,
            intent_type=DriverRouteIntentType.RETURN_LOAD,
        )
    )
    destination_intent = create_driver_route_intent(
        data=intent_data(
            organization=organization,
            driver=driver,
            intent_type=DriverRouteIntentType.DESTINATION_PREFERENCE,
            origin_city="São Paulo",
            origin_state="SP",
            destination_city="Belo Horizonte",
            destination_state="MG",
        )
    )
    assert isinstance(return_intent, DriverRouteIntent)
    assert isinstance(destination_intent, DriverRouteIntent)


@pytest.mark.django_db(transaction=True)
def test_route_compatibility_exact_partial_unknown(organization, django_user_model):
    user = django_user_model.objects.create_user(username="route-4", password="pass")
    driver = active_driver(organization=organization)
    now = timezone.now()
    intent = create_driver_route_intent(
        data=intent_data(
            organization=organization,
            driver=driver,
            available_from=now - timedelta(hours=1),
            available_until=now + timedelta(days=1),
        )
    )
    intent = activate_driver_route_intent(intent, actor=user)
    from src.customers.application.services import CustomerData, register_customer
    from src.customers.domain.enums import CustomerType

    customer = register_customer(
        data=CustomerData(
            organization=organization,
            customer_type=CustomerType.COMPANY,
            legal_name="Cliente Compat",
            document_number="11.222.333/0001-81",
            email="compat@example.com",
        )
    )
    offer_exact = published_offer(
        organization=organization,
        user=user,
        pickup=("Curitiba", "PR"),
        delivery=("São Paulo", "SP"),
        customer=customer,
    )
    offer_partial = published_offer(
        organization=organization,
        user=user,
        pickup=("Curitiba", "PR"),
        delivery=("Campinas", "SP"),
        customer=customer,
    )
    assert (
        evaluate_route_intent_compatibility(offer=offer_exact, route_intent=intent).level
        == RouteIntentCompatibilityLevel.EXACT
    )
    assert (
        evaluate_route_intent_compatibility(offer=offer_partial, route_intent=intent).level
        == RouteIntentCompatibilityLevel.PARTIAL
    )
    offer_exact.premises_snapshot = {}
    offer_exact.save(update_fields=["premises_snapshot"])
    assert (
        evaluate_route_intent_compatibility(offer=offer_exact, route_intent=intent).level
        == RouteIntentCompatibilityLevel.UNKNOWN
    )


@pytest.mark.django_db(transaction=True)
def test_tenant_isolation_and_idor(organization, other_organization, django_user_model, rbac_ready):
    owner = django_user_model.objects.create_user(username="route-owner", password="pass")
    outsider = django_user_model.objects.create_user(username="route-outsider", password="pass")
    grant(owner, organization, RoleCode.DISPATCHER)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN)
    driver = active_driver(organization=organization)
    intent = create_driver_route_intent(
        data=intent_data(organization=organization, driver=driver),
        actor=owner,
    )
    assert intent in scoped_driver_route_intent_queryset(
        owner, PermissionCode.DRIVER_ROUTE_INTENTS_VIEW
    )
    assert intent not in scoped_driver_route_intent_queryset(
        outsider, PermissionCode.DRIVER_ROUTE_INTENTS_VIEW
    )


@pytest.mark.django_db(transaction=True)
def test_salesperson_cannot_manage_route_intents(organization, django_user_model, rbac_ready):
    user = django_user_model.objects.create_user(username="route-sales", password="pass")
    grant(user, organization, RoleCode.SALESPERSON)
    assert not user_has_backoffice_permission(user, PermissionCode.DRIVER_ROUTE_INTENTS_CREATE)
    assert not user_has_backoffice_permission(user, PermissionCode.DRIVER_ROUTE_INTENTS_CANCEL)
