from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from src.compliance.domain.enums import DocumentStatus
from src.customers.application.services import CustomerData, register_customer
from src.customers.domain.enums import CustomerType
from src.drivers.application.route_intent_services import (
    DriverRouteIntentData,
    activate_driver_route_intent,
    cancel_driver_route_intent,
    create_driver_route_intent,
)
from src.drivers.domain.enums import DriverAvailabilityStatus, DriverDocumentType, DriverStatus
from src.drivers.domain.route_intent_enums import (
    DriverRouteIntentType,
    RouteIntentCargoPreference,
)
from src.drivers.infrastructure.django.models import Driver, DriverDocument
from src.freights.application.matching.services import (
    generate_match_candidates_for_offer,
    get_current_match_candidates,
)
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
from src.freights.domain.enums import (
    FreightCargoProfile,
    FreightRequestStatus,
    FreightStopType,
)
from src.freights.domain.matching_enums import MatchEligibilityStatus
from src.freights.domain.offer_enums import FreightOfferAudience
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization
from src.vehicles.application.services import (
    VehicleData,
    assign_driver_to_vehicle,
    register_vehicle,
)
from src.vehicles.domain.enums import (
    VehicleCargoProfile,
    VehicleDocumentType,
    VehicleOperationalStatus,
    VehicleStatus,
    VehicleType,
)
from src.vehicles.infrastructure.django.models import VehicleDocument


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Rotta Matching v2.1",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization():
    return Organization.objects.create(
        name="Other Matching v2.1",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


def make_customer(organization):
    return register_customer(
        data=CustomerData(
            organization=organization,
            customer_type=CustomerType.COMPANY,
            legal_name="Cliente v2.1",
            document_number="11.222.333/0001-81",
            email="matching-v2-1-cliente@example.com",
        )
    )


def submitted_request(
    *,
    organization,
    user,
    customer,
    cargo_profile=FreightCargoProfile.DRY_CARGO,
    pickup_city="Curitiba",
    pickup_state="PR",
    delivery_city="São Paulo",
    delivery_state="SP",
):
    cargo_kwargs = {
        "description": "Carga v2.1",
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
                    city=pickup_city,
                    state=pickup_state,
                ),
                StopData(
                    stop_type=FreightStopType.DELIVERY,
                    sequence=2,
                    city=delivery_city,
                    state=delivery_state,
                ),
            ),
            cargo=CargoData(**cargo_kwargs),
        ),
        actor=user,
    )
    submit_freight_request(request, actor=user)
    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=user)
    request.refresh_from_db()
    return request


def ready_request_with_quote(
    *,
    organization,
    user,
    customer,
    cargo_profile=FreightCargoProfile.DRY_CARGO,
    **kwargs,
):
    request = submitted_request(
        organization=organization,
        user=user,
        customer=customer,
        cargo_profile=cargo_profile,
        **kwargs,
    )
    quote = create_freight_quote(
        data=FreightQuoteData(
            freight_request=request,
            created_by=user,
            charges=(
                ChargeData(
                    charge_type=FreightQuoteChargeType.BASE_FREIGHT,
                    unit_amount=Decimal("5000"),
                ),
            ),
            valid_until="2026-12-31",
        ),
        actor=user,
    )
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    request.refresh_from_db()
    return request, quote


def published_offer(
    *,
    organization,
    user,
    audience=FreightOfferAudience.DRIVERS,
    cargo_profile=FreightCargoProfile.DRY_CARGO,
    **kwargs,
):
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization,
        user=user,
        customer=customer,
        cargo_profile=cargo_profile,
        **kwargs,
    )
    offer = create_freight_offer(
        data=FreightOfferData(
            freight_request=request,
            freight_quote=quote,
            created_by=user,
            offer_amount=Decimal("3500"),
            audience=audience,
            expires_at=timezone.now() + timedelta(days=7),
        ),
        actor=user,
    )
    offer = mark_freight_offer_ready(offer, actor=user)
    offer = publish_freight_offer(offer, actor=user)
    return offer


def compliant_vehicle(
    *,
    organization,
    plate,
    cargo_profile=VehicleCargoProfile.DRY_CARGO,
    **kwargs,
):
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate=plate,
            vehicle_type=VehicleType.VAN,
            cargo_profile=cargo_profile,
            operational_status=VehicleOperationalStatus.AVAILABLE,
            status=VehicleStatus.ACTIVE,
            **kwargs,
        )
    )
    VehicleDocument.objects.create(
        vehicle=vehicle,
        document_type=VehicleDocumentType.CRLV.value,
        storage_key=f"vehicles/{plate}/crlv.pdf",
        status=DocumentStatus.APPROVED.value,
    )
    return vehicle


def active_driver(*, organization, name="Motorista Matching v2.1", compliant=False):
    driver = Driver.objects.create(
        organization=organization,
        full_name=name,
        status=DriverStatus.ACTIVE.value,
        availability_status=DriverAvailabilityStatus.AVAILABLE.value,
    )
    if compliant:
        DriverDocument.objects.create(
            driver=driver,
            document_type=DriverDocumentType.DRIVER_LICENSE.value,
            storage_key=f"drivers/{driver.id}/cnh.pdf",
            status=DocumentStatus.APPROVED.value,
            expiration_date=timezone.localdate() + timedelta(days=365),
        )
    return driver


def make_active_intent(
    *,
    organization,
    driver,
    vehicle=None,
    intent_type=DriverRouteIntentType.RETURN_LOAD,
    origin_city="Curitiba",
    origin_state="PR",
    destination_city="São Paulo",
    destination_state="SP",
    available_from=None,
    available_until=None,
    cargo_preference=RouteIntentCargoPreference.BOTH,
    actor=None,
):
    if available_from is None:
        available_from = timezone.now() - timedelta(hours=1)
    if available_until is None:
        available_until = timezone.now() + timedelta(days=2)

    intent = create_driver_route_intent(
        data=DriverRouteIntentData(
            organization=organization,
            driver=driver,
            vehicle=vehicle,
            intent_type=intent_type,
            origin_city=origin_city,
            origin_state=origin_state,
            destination_city=destination_city,
            destination_state=destination_state,
            available_from=available_from,
            available_until=available_until,
            cargo_preference=cargo_preference,
            notes="Intent test matching",
        ),
        actor=actor,
    )
    return activate_driver_route_intent(intent, actor=actor)


@pytest.mark.django_db(transaction=True)
def test_exact_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="exact-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="EXA1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generation = generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    assert generation.algorithm_version == "v2.1"

    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.score_explanation["route_intent"]["compatibility"] == "EXACT"
    assert cand.score_explanation["route_intent"]["bonus"] == 5.0
    assert cand.score_explanation["final_score"] == float(cand.total_score)
    assert cand.score_explanation["base_score"] > 0
    assert "route_intent_id" in cand.score_explanation["route_intent"]


@pytest.mark.django_db(transaction=True)
def test_partial_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="partial-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="PAR1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="Campinas",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.score_explanation["route_intent"]["compatibility"] == "PARTIAL"
    assert cand.score_explanation["route_intent"]["bonus"] == 2.5


@pytest.mark.django_db(transaction=True)
def test_incompatible_route_intent_does_not_block(organization, django_user_model):
    user = django_user_model.objects.create_user(username="incompat-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="INC1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Porto Alegre",
        origin_state="RS",
        destination_city="Curitiba",
        destination_state="PR",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.eligibility_status == MatchEligibilityStatus.ELIGIBLE.value
    assert cand.score_explanation["route_intent"]["compatibility"] == "INCOMPATIBLE"
    assert cand.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand.score_explanation["final_score"] == cand.score_explanation["base_score"]


@pytest.mark.django_db(transaction=True)
def test_no_intent_neutral(organization, django_user_model):
    user = django_user_model.objects.create_user(username="nointent-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="NOI1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    offer = published_offer(
        organization=organization,
        user=user,
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.score_explanation["route_intent"]["compatibility"] == "UNKNOWN"
    assert cand.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand.score_explanation["final_score"] == cand.score_explanation["base_score"]


@pytest.mark.django_db(transaction=True)
def test_multiple_route_intents_selects_best(organization, django_user_model):
    user = django_user_model.objects.create_user(username="multi-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="MUL1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    # Incompatible intent
    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Rio de Janeiro",
        origin_state="RJ",
        destination_city="Belo Horizonte",
        destination_state="MG",
        actor=user,
    )
    # Exact intent (should be chosen)
    exact_intent = make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.score_explanation["route_intent"]["compatibility"] == "EXACT"
    assert cand.score_explanation["route_intent"]["bonus"] == 5.0
    assert cand.score_explanation["route_intent"]["route_intent_id"] == str(exact_intent.id)


@pytest.mark.django_db(transaction=True)
def test_vehicle_specific_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="vehicle-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="VEH1111")
    vehicle_b = compliant_vehicle(organization=organization, plate="VEH2222")

    # Assign driver to vehicle_a first to allow registering vehicle-specific intent
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle_a, valid_from=date.today())

    # Intent linked to vehicle_a
    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle_a,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    # Candidate with Driver + Vehicle B
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle_b, valid_from=date.today())
    from src.vehicles.infrastructure.django.models import DriverVehicleAssignment

    DriverVehicleAssignment.objects.filter(driver=driver, vehicle=vehicle_a).update(active=False)

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    # Should not benefit from vehicle_a intent, falls back to UNKNOWN (neutral bonus = 0)
    assert cand.score_explanation["route_intent"]["compatibility"] == "UNKNOWN"
    assert cand.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand.score_explanation["final_score"] == cand.score_explanation["base_score"]


@pytest.mark.django_db(transaction=True)
def test_expired_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="expired-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="EXP1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    # Create active intent
    intent = make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )
    # Manually expire it in database to simulate passage of time
    from src.drivers.infrastructure.django.models import DriverRouteIntent

    DriverRouteIntent.objects.filter(pk=intent.pk).update(
        available_from=timezone.now() - timedelta(days=5),
        available_until=timezone.now() - timedelta(days=1),
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.score_explanation["route_intent"]["compatibility"] == "UNKNOWN"
    assert cand.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand.score_explanation["final_score"] == cand.score_explanation["base_score"]


@pytest.mark.django_db(transaction=True)
def test_cancelled_route_intent(organization, django_user_model):
    user = django_user_model.objects.create_user(username="cancelled-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="CAN1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    intent = make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )
    cancel_driver_route_intent(intent, actor=user, reason="Changed plans")

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.score_explanation["route_intent"]["compatibility"] == "UNKNOWN"
    assert cand.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand.score_explanation["final_score"] == cand.score_explanation["base_score"]


@pytest.mark.django_db(transaction=True)
def test_refrigerated_cargo_sovereign_rule(organization, django_user_model):
    user = django_user_model.objects.create_user(username="refrigerated-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(
        organization=organization,
        plate="REF1234",
        cargo_profile=VehicleCargoProfile.DRY_CARGO,  # Non-refrigerated vehicle!
    )
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.eligibility_status == MatchEligibilityStatus.INELIGIBLE.value


@pytest.mark.django_db(transaction=True)
def test_compliance_sovereign_rule(organization, django_user_model):
    user = django_user_model.objects.create_user(username="compliance-v21", password="pass")
    driver = active_driver(
        organization=organization,
        compliant=False,  # Missing document license document! Non-compliant!
    )
    vehicle = compliant_vehicle(organization=organization, plate="COM1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)
    cand = [c for c in candidates if c.driver == driver][0]

    assert cand.eligibility_status == MatchEligibilityStatus.INELIGIBLE.value


@pytest.mark.django_db(transaction=True)
def test_ranking_advantage_rule(organization, django_user_model):
    user = django_user_model.objects.create_user(username="ranking-v21", password="pass")

    # Driver A: No active route intent
    driver_a = active_driver(organization=organization, name="Driver A", compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="RAN1111")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())

    # Driver B: Exact active route intent
    driver_b = active_driver(organization=organization, name="Driver B", compliant=True)
    vehicle_b = compliant_vehicle(organization=organization, plate="RAN2222")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())
    make_active_intent(
        organization=organization,
        driver=driver_b,
        vehicle=vehicle_b,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)

    cand_a = [c for c in candidates if c.driver == driver_a][0]
    cand_b = [c for c in candidates if c.driver == driver_b][0]

    assert cand_a.eligibility_status == MatchEligibilityStatus.ELIGIBLE.value
    assert cand_b.eligibility_status == MatchEligibilityStatus.ELIGIBLE.value

    assert cand_b.total_score > cand_a.total_score
    assert cand_b.rank_position < cand_a.rank_position


@pytest.mark.django_db(transaction=True)
def test_tenant_isolation_rule(organization, other_organization, django_user_model):
    user = django_user_model.objects.create_user(username="tenant-v21", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="TEN1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    # Offer belongs to other_organization (Tenant B)
    offer = published_offer(
        organization=other_organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    from src.freights.application.matching.eligibility import EligibilityResult
    from src.freights.application.matching.scoring import compute_scores

    eligibility = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    scores = compute_scores(
        offer=offer,
        eligibility=eligibility,
        driver=driver,
        vehicle=vehicle,
    )

    assert scores.explanation["route_intent"]["compatibility"] == "UNKNOWN"
    assert scores.explanation["route_intent"]["bonus"] == 0.0
    assert scores.explanation["final_score"] == scores.explanation["base_score"]


# Semantic Regression Tests A-F


@pytest.mark.django_db(transaction=True)
def test_semantic_no_intent_does_not_reduce_score(organization, django_user_model):
    user = django_user_model.objects.create_user(username="semantic-a", password="pass")
    driver_a = active_driver(organization=organization, name="Driver A", compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="AAA1234")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())

    driver_b = active_driver(organization=organization, name="Driver B", compliant=True)
    vehicle_b = compliant_vehicle(organization=organization, plate="BBB1234")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())

    # Driver B has INCOMPATIBLE intent
    make_active_intent(
        organization=organization,
        driver=driver_b,
        vehicle=vehicle_b,
        origin_city="Porto Alegre",
        origin_state="RS",
        destination_city="Belo Horizonte",
        destination_state="MG",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)

    cand_a = [c for c in candidates if c.driver == driver_a][0]
    cand_b = [c for c in candidates if c.driver == driver_b][0]

    assert cand_a.total_score == cand_b.total_score
    assert cand_a.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand_b.score_explanation["route_intent"]["bonus"] == 0.0


@pytest.mark.django_db(transaction=True)
def test_semantic_exact_benefits(organization, django_user_model):
    user = django_user_model.objects.create_user(username="semantic-b", password="pass")
    driver_a = active_driver(organization=organization, name="Driver A", compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="AAA1234")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())

    driver_b = active_driver(organization=organization, name="Driver B", compliant=True)
    vehicle_b = compliant_vehicle(organization=organization, plate="BBB1234")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())

    # Driver B has EXACT intent
    make_active_intent(
        organization=organization,
        driver=driver_b,
        vehicle=vehicle_b,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)

    cand_a = [c for c in candidates if c.driver == driver_a][0]
    cand_b = [c for c in candidates if c.driver == driver_b][0]

    assert cand_b.total_score > cand_a.total_score
    assert cand_b.total_score == cand_a.total_score + Decimal("5.0")


@pytest.mark.django_db(transaction=True)
def test_semantic_exact_greater_than_partial_greater_than_none(organization, django_user_model):
    user = django_user_model.objects.create_user(username="semantic-c", password="pass")
    # Driver A: None
    driver_a = active_driver(organization=organization, name="Driver A", compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="AAA1234")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())

    # Driver B: Partial
    driver_b = active_driver(organization=organization, name="Driver B", compliant=True)
    vehicle_b = compliant_vehicle(organization=organization, plate="BBB1234")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())
    make_active_intent(
        organization=organization,
        driver=driver_b,
        vehicle=vehicle_b,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="Campinas",
        destination_state="SP",
        actor=user,
    )

    # Driver C: Exact
    driver_c = active_driver(organization=organization, name="Driver C", compliant=True)
    vehicle_c = compliant_vehicle(organization=organization, plate="CCC1234")
    assign_driver_to_vehicle(driver=driver_c, vehicle=vehicle_c, valid_from=date.today())
    make_active_intent(
        organization=organization,
        driver=driver_c,
        vehicle=vehicle_c,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)

    cand_a = [c for c in candidates if c.driver == driver_a][0]
    cand_b = [c for c in candidates if c.driver == driver_b][0]
    cand_c = [c for c in candidates if c.driver == driver_c][0]

    assert cand_c.total_score > cand_b.total_score
    assert cand_b.total_score > cand_a.total_score

    assert cand_c.score_explanation["route_intent"]["bonus"] == 5.0
    assert cand_b.score_explanation["route_intent"]["bonus"] == 2.5
    assert cand_a.score_explanation["route_intent"]["bonus"] == 0.0


@pytest.mark.django_db(transaction=True)
def test_semantic_incompatible_not_penalize(organization, django_user_model):
    user = django_user_model.objects.create_user(username="semantic-d", password="pass")
    driver_a = active_driver(organization=organization, name="Driver A", compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="AAA1234")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())

    driver_b = active_driver(organization=organization, name="Driver B", compliant=True)
    vehicle_b = compliant_vehicle(organization=organization, plate="BBB1234")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())

    # Driver B has INCOMPATIBLE intent
    make_active_intent(
        organization=organization,
        driver=driver_b,
        vehicle=vehicle_b,
        origin_city="Porto Alegre",
        origin_state="RS",
        destination_city="Belo Horizonte",
        destination_state="MG",
        actor=user,
    )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)

    cand_a = [c for c in candidates if c.driver == driver_a][0]
    cand_b = [c for c in candidates if c.driver == driver_b][0]

    assert cand_a.total_score == cand_b.total_score


@pytest.mark.django_db(transaction=True)
def test_semantic_unknown_not_penalize(organization, django_user_model):
    user = django_user_model.objects.create_user(username="semantic-e", password="pass")
    driver_a = active_driver(organization=organization, name="Driver A", compliant=True)
    vehicle_a = compliant_vehicle(organization=organization, plate="AAA1234")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())

    driver_b = active_driver(organization=organization, name="Driver B", compliant=True)
    vehicle_b = compliant_vehicle(organization=organization, plate="BBB1234")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())

    # Driver B has UNKNOWN intent (represented as route compatibility unknown)
    intent = make_active_intent(
        organization=organization,
        driver=driver_b,
        vehicle=vehicle_b,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        cargo_preference=RouteIntentCargoPreference.BOTH,
        actor=user,
    )
    from src.drivers.infrastructure.django.models import DriverRouteIntent

    DriverRouteIntent.objects.filter(pk=intent.pk).update(origin_city="")

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    candidates = get_current_match_candidates(offer)

    cand_a = [c for c in candidates if c.driver == driver_a][0]
    cand_b = [c for c in candidates if c.driver == driver_b][0]

    # Without matching bonus (both get 0.0 bonus), scores must remain equivalent
    assert cand_a.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand_b.score_explanation["route_intent"]["bonus"] == 0.0
    assert cand_a.total_score == cand_b.total_score


@pytest.mark.django_db(transaction=True)
def test_semantic_clamp_at_100(organization, django_user_model):
    user = django_user_model.objects.create_user(username="semantic-f", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="CLA1234")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    make_active_intent(
        organization=organization,
        driver=driver,
        vehicle=vehicle,
        origin_city="Curitiba",
        origin_state="PR",
        destination_city="São Paulo",
        destination_state="SP",
        actor=user,
    )

    # Let's call compute_scores directly with high base score
    from src.freights.application.matching.eligibility import EligibilityResult
    from src.freights.application.matching.scoring import compute_scores

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    eligibility = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    scores = compute_scores(
        offer=offer,
        eligibility=eligibility,
        driver=driver,
        vehicle=vehicle,
    )

    # Base score is close to 100, adding EXACT (+5) should clamp final score to 100.0
    assert scores.explanation["final_score"] <= 100.0


@pytest.mark.django_db(transaction=True)
def test_n_plus_one_query_performance_audit(organization, django_user_model):
    user = django_user_model.objects.create_user(username="performance-audit", password="pass")

    # Register multiple compliant drivers & vehicles to increase candidate count
    for i in range(5):
        drv = active_driver(organization=organization, name=f"Driver {i}", compliant=True)
        vh = compliant_vehicle(organization=organization, plate=f"AUD123{i}")
        assign_driver_to_vehicle(driver=drv, vehicle=vh, valid_from=date.today())
        make_active_intent(
            organization=organization,
            driver=drv,
            vehicle=vh,
            origin_city="Curitiba",
            origin_state="PR",
            destination_city="São Paulo",
            destination_state="SP",
            actor=user,
        )

    offer = published_offer(
        organization=organization,
        user=user,
        pickup_city="Curitiba",
        pickup_state="PR",
        delivery_city="São Paulo",
        delivery_state="SP",
    )

    with CaptureQueriesContext(connection) as ctx:
        generate_match_candidates_for_offer(offer, actor=user, regenerate=True)

    # Identify matching route intent query
    route_intent_queries = [
        q for q in ctx.captured_queries if "drivers_driverrouteintent" in q["sql"]
    ]

    # Verify that ONLY ONE query was executed to pull route intents in bulk
    assert len(route_intent_queries) == 1
