import pytest
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from django.core.management import call_command
from django.utils import timezone

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.customers.application.services import CustomerData, register_customer
from src.customers.domain.enums import CustomerType
from src.drivers.domain.enums import DriverAvailabilityStatus, DriverStatus, DriverDocumentType
from src.drivers.domain.route_intent_enums import DriverRouteIntentType, DriverRouteIntentStatus
from src.drivers.infrastructure.django.models import Driver, DriverPreference, DriverRegionPreference, DriverRegionPreferenceType, DriverRouteIntent, DriverDocument
from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus
from src.carriers.infrastructure.django.models import CarrierProfile, CarrierDriverLink, CarrierVehicleLink
from src.compliance.domain.enums import DocumentStatus
from src.vehicles.domain.enums import VehicleDocumentType
from src.vehicles.infrastructure.django.models import VehicleDocument
from src.freights.application.matching.constants import MATCHING_ALGORITHM_VERSION
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
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.freights.domain.offer_enums import FreightOfferAudience
from src.freights.domain.matching_enums import MatchEligibilityStatus
from src.vehicles.application.services import (
    VehicleData,
    assign_driver_to_vehicle,
    register_vehicle,
)
from src.vehicles.domain.enums import (
    VehicleCargoProfile,
    VehicleOperationalStatus,
    VehicleStatus,
    VehicleType,
)
from src.vehicles.infrastructure.django.models import Vehicle, DriverVehicleAssignment


@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def tenant(db):
    return Organization.objects.create(name="Rotta Tenant", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def other_tenant(db):
    return Organization.objects.create(name="Other Tenant", type=OrganizationType.TRANSPORT_COMPANY)


@pytest.fixture
def user_backoffice(db, django_user_model, tenant):
    user = django_user_model.objects.create_user(username="ops-user", password="password")
    grant(user, tenant, RoleCode.OPERATIONS_MANAGER.value)
    return user


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership, _ = Membership.objects.get_or_create(user=user, organization=organization, defaults={"status": "ACTIVE"})
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.get_or_create(membership=membership, role=role, defaults={"scope": scope})
    return membership


def make_customer(organization):
    return register_customer(
        data=CustomerData(
            organization=organization,
            customer_type=CustomerType.COMPANY,
            legal_name="Cliente Matching",
            document_number="11.222.333/0001-81",
            email="matching-cliente@example.com",
        )
    )


def create_compliant_driver(*, organization, user, name="Motorista Matching", status=DriverStatus.ACTIVE.value):
    driver = Driver.objects.create(
        organization=organization,
        user=user,
        full_name=name,
        status=status,
        availability_status=DriverAvailabilityStatus.AVAILABLE.value,
    )
    DriverDocument.objects.create(
        driver=driver,
        document_type=DriverDocumentType.DRIVER_LICENSE.value,
        storage_key=f"drivers/{driver.id}/cnh.pdf",
        status=DocumentStatus.APPROVED.value,
        expiration_date=timezone.localdate() + timedelta(days=365),
    )
    return driver


def create_compliant_vehicle(*, organization, plate, cargo_profile=VehicleCargoProfile.DRY_CARGO, status=VehicleStatus.ACTIVE):
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate=plate,
            vehicle_type=VehicleType.VAN,
            cargo_profile=cargo_profile,
            operational_status=VehicleOperationalStatus.AVAILABLE,
            status=status,
        )
    )
    VehicleDocument.objects.get_or_create(
        vehicle=vehicle,
        document_type=VehicleDocumentType.CRLV.value,
        defaults={
            "storage_key": f"vehicles/{plate}/crlv.pdf",
            "status": DocumentStatus.APPROVED.value,
        }
    )
    return vehicle


def build_offer(
    *,
    organization,
    user,
    pickup_city="Itapevi",
    pickup_lat=Decimal("-23.5489"),
    pickup_lon=Decimal("-46.9314"),
    delivery_city="Sorocaba",
    delivery_lat=Decimal("-23.5015"),
    delivery_lon=Decimal("-47.4581"),
    cargo_profile=FreightCargoProfile.DRY_CARGO,
):
    customer = make_customer(organization)
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
                    state="SP",
                    latitude=pickup_lat,
                    longitude=pickup_lon,
                ),
                StopData(
                    stop_type=FreightStopType.DELIVERY,
                    sequence=2,
                    city=delivery_city,
                    state="SP",
                    latitude=delivery_lat,
                    longitude=delivery_lon,
                ),
            ),
            cargo=CargoData(
                description="General Cargo",
                weight_kg=Decimal("1000"),
                cargo_profile=cargo_profile,
            ),
        ),
        actor=user,
    )
    submit_freight_request(request, actor=user)
    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=user)
    request.refresh_from_db()

    quote = create_freight_quote(
        data=FreightQuoteData(
            freight_request=request,
            created_by=user,
            charges=(
                ChargeData(
                    charge_type=FreightQuoteChargeType.BASE_FREIGHT,
                    unit_amount=Decimal("3000"),
                ),
            ),
            valid_until="2026-12-31",
        ),
        actor=user,
    )
    submit_freight_quote_for_review(quote, actor=user)
    approve_freight_quote(quote, actor=user)
    request.refresh_from_db()

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
    mark_freight_offer_ready(offer, actor=user)
    publish_freight_offer(offer, actor=user)
    return offer


@pytest.mark.django_db(transaction=True)
def test_matching_v3_scores_and_preferences(rbac_ready, tenant, other_tenant, user_backoffice, django_user_model):
    # 1. Create a published offer with known coordinates (Itapevi to Sorocaba)
    offer = build_offer(organization=tenant, user=user_backoffice)

    # 2. Create Driver A in target tenant
    user_a = django_user_model.objects.create_user(username="driver_a_user", password="password")
    driver_a = create_compliant_driver(organization=tenant, user=user_a, name="Driver A")
    # Give driver a vehicle to pass candidate generation specs requirements
    vehicle_a = create_compliant_vehicle(organization=tenant, plate="AAA1A11")
    DriverVehicleAssignment.objects.create(
        driver=driver_a,
        vehicle=vehicle_a,
        active=True,
        valid_from=timezone.now().date(),
    )

    # 3. Create Driver B in OTHER tenant (must NOT appear in matching candidates)
    user_b = django_user_model.objects.create_user(username="driver_b_user", password="password")
    driver_b = create_compliant_driver(organization=other_tenant, user=user_b, name="Driver B")
    vehicle_b = create_compliant_vehicle(organization=other_tenant, plate="BBB1B11")
    DriverVehicleAssignment.objects.create(
        driver=driver_b,
        vehicle=vehicle_b,
        active=True,
        valid_from=timezone.now().date(),
    )

    # 4. Create Driver C in target tenant WITHOUT preferences (cold-start baseline candidate)
    user_c = django_user_model.objects.create_user(username="driver_c_user", password="password")
    driver_c = create_compliant_driver(organization=tenant, user=user_c, name="Driver C")
    vehicle_c = create_compliant_vehicle(organization=tenant, plate="CCC1C11")
    DriverVehicleAssignment.objects.create(
        driver=driver_c,
        vehicle=vehicle_c,
        active=True,
        valid_from=timezone.now().date(),
    )

    # 5. Set up Driver A preferences: Base in Itapevi (exact match of pickup)
    pref_a = DriverPreference.objects.create(
        driver=driver_a,
        base_city="Itapevi",
        base_state="SP",
        base_postal_code="06696-000",
        base_latitude=Decimal("-23.5489"),
        base_longitude=Decimal("-46.9314"),
        preferred_radius_km=50,
    )

    # 6. Run Matching V3 candidate generation
    generation = generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    assert generation.algorithm_version == "v3.0"

    candidates = list(get_current_match_candidates(offer))

    # Assert isolation: Driver B (from another organization) must NOT be present
    assert not any(c.driver_id == driver_b.id for c in candidates)

    # Baseline checks
    cand_a = next(c for c in candidates if c.driver_id == driver_a.id)
    cand_c = next(c for c in candidates if c.driver_id == driver_c.id)

    # Check breakdown matches and persistence
    assert cand_a.algorithm_version == "v3.0"
    exp_a = cand_a.score_explanation
    assert exp_a["eligibility"] == "passed"
    assert "vehicle_fit" in exp_a
    assert "cargo_fit" in exp_a
    assert "geographic_fit" in exp_a
    assert "route_fit" in exp_a
    assert "preference_fit" in exp_a
    assert "total_score" in exp_a
    assert "WITHIN_PREFERRED_RADIUS" in exp_a["explanation_codes"]

    # Driver A has geographic score close to 100 because base is exact match of pickup
    assert exp_a["geographic_fit"] == 100.0

    # Driver C without preferences has neutral geographic_fit of 50.0
    exp_c = cand_c.score_explanation
    assert exp_c["geographic_fit"] == 50.0

    # Driver A should score higher than Driver C due to geographic preferences match
    assert cand_a.total_score > cand_c.total_score


@pytest.mark.django_db(transaction=True)
def test_matching_v3_regions_avoid_prefer_and_intents(rbac_ready, tenant, user_backoffice, django_user_model):
    offer = build_offer(organization=tenant, user=user_backoffice)

    # Driver A
    user_a = django_user_model.objects.create_user(username="driver_a", password="password")
    driver_a = create_compliant_driver(organization=tenant, user=user_a, name="Driver A")
    vehicle_a = create_compliant_vehicle(organization=tenant, plate="AAA1A11")
    DriverVehicleAssignment.objects.create(
        driver=driver_a,
        vehicle=vehicle_a,
        active=True,
        valid_from=timezone.now().date(),
    )

    # Preferences: Base is far (Rio de Janeiro), so base score is low
    pref_a = DriverPreference.objects.create(
        driver=driver_a,
        base_city="Rio de Janeiro",
        base_state="RJ",
        base_latitude=Decimal("-22.9068"),
        base_longitude=Decimal("-43.1729"),
        preferred_radius_km=50,
    )

    # Add Preferred Region: Sorocaba/SP (which is the delivery destination)
    DriverRegionPreference.objects.create(
        driver=driver_a,
        city="Sorocaba",
        state="SP",
        preference_type=DriverRegionPreferenceType.PREFER,
    )

    # Run matching - Driver A geographic score has region bonus
    generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    cand = next(c for c in get_current_match_candidates(offer) if c.driver_id == driver_a.id)
    exp = cand.score_explanation
    assert "PREFERRED_REGION_MATCH" in exp["explanation_codes"]
    score_with_prefer = exp["geographic_fit"]

    # Now change region preference to AVOID Sorocaba/SP
    driver_a.region_preferences.all().delete()
    DriverRegionPreference.objects.create(
        driver=driver_a,
        city="Sorocaba",
        state="SP",
        preference_type=DriverRegionPreferenceType.AVOID,
    )

    generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    cand = next(c for c in get_current_match_candidates(offer) if c.driver_id == driver_a.id)
    exp = cand.score_explanation
    assert "AVOID_REGION" in exp["explanation_codes"]
    assert exp["geographic_fit"] < score_with_prefer

    # Test DESTINATION_PREFERENCE RouteIntent
    # Add active DESTINATION_PREFERENCE matching delivery city Sorocaba
    tomorrow = timezone.now() + timedelta(days=1)
    day_after = tomorrow + timedelta(days=1)
    intent = DriverRouteIntent.objects.create(
        organization=tenant,
        driver=driver_a,
        intent_type=DriverRouteIntentType.DESTINATION_PREFERENCE.value,
        origin_city="Itapevi",
        origin_state="SP",
        destination_city="Sorocaba",
        destination_state="SP",
        available_from=tomorrow,
        available_until=day_after,
        status=DriverRouteIntentStatus.ACTIVE.value,
    )

    generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    cand = next(c for c in get_current_match_candidates(offer) if c.driver_id == driver_a.id)
    exp = cand.score_explanation
    assert "DESTINATION_MATCH" in exp["explanation_codes"]
    assert exp["route_fit"] == 100.0


@pytest.mark.django_db(transaction=True)
def test_matching_v3_hard_constraints_prevail(rbac_ready, tenant, user_backoffice, django_user_model):
    offer = build_offer(organization=tenant, user=user_backoffice)

    # Driver A - Perfect matching preferences, but has no compliant documents (hard constraint failure)
    user_a = django_user_model.objects.create_user(username="driver_a", password="password")
    driver_a = Driver.objects.create(
        organization=tenant,
        user=user_a,
        full_name="Driver A",
        status=DriverStatus.ACTIVE.value,
        availability_status=DriverAvailabilityStatus.AVAILABLE.value,
    )
    vehicle_a = create_compliant_vehicle(organization=tenant, plate="AAA1A11")
    DriverVehicleAssignment.objects.create(
        driver=driver_a,
        vehicle=vehicle_a,
        active=True,
        valid_from=timezone.now().date(),
    )
    DriverPreference.objects.create(
        driver=driver_a,
        base_city="Itapevi",
        base_state="SP",
        base_latitude=Decimal("-23.5489"),
        base_longitude=Decimal("-46.9314"),
        preferred_radius_km=50,
    )

    generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    cand = next(c for c in get_current_match_candidates(offer) if c.driver_id == driver_a.id)
    # Must be INELIGIBLE because driver lacks compliant documents
    assert cand.eligibility_status == MatchEligibilityStatus.INELIGIBLE.value


@pytest.mark.django_db(transaction=True)
def test_matching_v3_determinism(rbac_ready, tenant, user_backoffice, django_user_model):
    offer = build_offer(organization=tenant, user=user_backoffice)

    # Create 3 identical drivers with identical vehicle assignments
    for i in range(3):
        user = django_user_model.objects.create_user(username=f"driver_{i}", password="password")
        driver = create_compliant_driver(organization=tenant, user=user, name=f"Driver {i}")
        vehicle = create_compliant_vehicle(organization=tenant, plate=f"DDD1D{i}1")
        DriverVehicleAssignment.objects.create(
            driver=driver,
            vehicle=vehicle,
            active=True,
            valid_from=timezone.now().date(),
        )

    # Run matching twice and compare scores and rank positions
    generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    run1 = [(c.driver_id, float(c.total_score), c.rank_position) for c in get_current_match_candidates(offer)]

    generate_match_candidates_for_offer(offer=offer, actor=user_backoffice, regenerate=True)
    run2 = [(c.driver_id, float(c.total_score), c.rank_position) for c in get_current_match_candidates(offer)]

    assert run1 == run2
