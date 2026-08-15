from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus
from src.carriers.infrastructure.django.models import CarrierProfile
from src.compliance.domain.enums import DocumentStatus
from src.customers.application.services import CustomerData, register_customer
from src.customers.domain.enums import CustomerType
from src.drivers.domain.enums import DriverAvailabilityStatus, DriverDocumentType, DriverStatus
from src.drivers.infrastructure.django.models import Driver, DriverDocument
from src.freights.application.matching.constants import MATCHING_ALGORITHM_VERSION
from src.freights.application.matching.eligibility import (
    evaluate_carrier_eligibility,
    evaluate_private_target_access,
    evaluate_vehicle_eligibility,
    load_private_target_ids,
)
from src.freights.application.matching.invitation_services import (
    cancel_freight_offer_invitation,
    invite_match_candidate,
)
from src.freights.application.matching.services import (
    generate_match_candidates_for_offer,
    get_current_match_candidates,
)
from src.freights.application.offer_services import (
    FreightOfferData,
    add_freight_offer_target,
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
from src.freights.domain.matching_enums import (
    FreightOfferInvitationStatus,
    InvitationDeclineReason,
    MatchEligibilityReasonCode,
    MatchEligibilityStatus,
)
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.freights.infrastructure.django.models import (
    FreightMatchCandidate,
    FreightMatchGeneration,
    FreightOfferInvitation,
    MarketplaceEvent,
)
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.models import MembershipRole, Role
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope
from src.shared.interfaces.backoffice.authorization import (
    scoped_freight_match_candidate_queryset,
    scoped_freight_offer_invitation_queryset,
    user_has_backoffice_permission,
)
from src.vehicles.application.services import (
    RefrigerationProfileData,
    VehicleData,
    assign_driver_to_vehicle,
    register_vehicle,
    upsert_refrigeration_profile,
)
from src.vehicles.domain.enums import (
    VehicleCargoProfile,
    VehicleDocumentType,
    VehicleOperationalStatus,
    VehicleStatus,
    VehicleType,
)
from src.vehicles.infrastructure.django.models import Vehicle, VehicleDocument


@pytest.fixture
def rbac_ready():
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Rotta Matching",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization():
    return Organization.objects.create(
        name="Outra Matching",
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
            legal_name="Cliente Matching",
            document_number="11.222.333/0001-81",
            email="matching-cliente@example.com",
        )
    )


def submitted_request(
    *,
    organization,
    user,
    customer,
    cargo_profile=FreightCargoProfile.DRY_CARGO,
):
    cargo_kwargs = {
        "description": "Carga matching",
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


def ready_request_with_quote(*, organization, user, customer, cargo_profile=FreightCargoProfile.DRY_CARGO):
    request = submitted_request(
        organization=organization,
        user=user,
        customer=customer,
        cargo_profile=cargo_profile,
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


def make_carrier(*, tenant, email="carrier@example.com", **kwargs):
    carrier_org = Organization.objects.create(
        name=f"Carrier Org {email}",
        type=OrganizationType.PARTNER,
    )
    defaults = {
        "status": CarrierStatus.ACTIVE.value,
        "cargo_profile": CarrierCargoProfile.BOTH.value,
    }
    defaults.update(kwargs)
    return CarrierProfile.objects.create(
        organization=carrier_org,
        tenant=tenant,
        email=email,
        **defaults,
    )


def published_offer(
    *,
    organization,
    user,
    audience=FreightOfferAudience.CARRIERS,
    cargo_profile=FreightCargoProfile.DRY_CARGO,
    targets=(),
):
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(
        organization=organization,
        user=user,
        customer=customer,
        cargo_profile=cargo_profile,
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
    for target in targets:
        if target.get("carrier"):
            add_freight_offer_target(offer, carrier=target["carrier"], actor=user)
        if target.get("driver"):
            add_freight_offer_target(offer, driver=target["driver"], actor=user)
    offer = mark_freight_offer_ready(offer, actor=user)
    offer = publish_freight_offer(offer, actor=user)
    return offer


def compliant_vehicle(*, organization, plate, cargo_profile=VehicleCargoProfile.DRY_CARGO, **kwargs):
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


def active_driver(*, organization, name="Motorista Matching", compliant=False):
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


@pytest.mark.django_db(transaction=True)
def test_generate_matching_creates_ranked_candidates(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-1", password="pass")
    make_carrier(tenant=organization, email="c1@example.com")
    make_carrier(tenant=organization, email="c2@example.com")
    offer = published_offer(organization=organization, user=user)

    generation = generate_match_candidates_for_offer(offer, actor=user)
    candidates = list(get_current_match_candidates(offer))

    assert generation.is_current is True
    assert generation.algorithm_version == MATCHING_ALGORITHM_VERSION
    assert generation.candidate_count == len(candidates)
    assert generation.candidate_count >= 2
    assert all(candidate.algorithm_version == MATCHING_ALGORITHM_VERSION for candidate in candidates)
    assert candidates[0].rank_position == 1
    assert candidates[0].total_score is not None
    assert "compliance" in candidates[0].score_explanation
    assert AuditLog.objects.filter(action="freight_matching_generated", target_id=str(offer.id)).exists()


@pytest.mark.django_db(transaction=True)
def test_matching_idempotent_without_regenerate(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-2", password="pass")
    make_carrier(tenant=organization, email="c3@example.com")
    offer = published_offer(organization=organization, user=user)

    first = generate_match_candidates_for_offer(offer, actor=user, regenerate=False)
    second = generate_match_candidates_for_offer(offer, actor=user, regenerate=False)

    assert first.id == second.id
    assert FreightMatchGeneration.objects.filter(offer=offer).count() == 1


@pytest.mark.django_db(transaction=True)
def test_matching_regeneration_preserves_history(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-3", password="pass")
    make_carrier(tenant=organization, email="c4@example.com")
    offer = published_offer(organization=organization, user=user)

    first = generate_match_candidates_for_offer(offer, actor=user, regenerate=False)
    second = generate_match_candidates_for_offer(offer, actor=user, regenerate=True)

    first.refresh_from_db()
    assert first.is_current is False
    assert second.is_current is True
    assert second.generation_number == 2
    assert FreightMatchGeneration.objects.filter(offer=offer).count() == 2
    assert AuditLog.objects.filter(action="freight_matching_regenerated", target_id=str(offer.id)).exists()


@pytest.mark.django_db(transaction=True)
def test_inactive_carrier_is_ineligible(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-4", password="pass")
    blocked = make_carrier(
        tenant=organization,
        email="blocked@example.com",
        status=CarrierStatus.BLOCKED.value,
    )
    offer = published_offer(organization=organization, user=user)
    result = evaluate_carrier_eligibility(offer=offer, carrier=blocked)
    assert result.status == MatchEligibilityStatus.INELIGIBLE
    assert any(
        reason.code == MatchEligibilityReasonCode.ENTITY_INACTIVE for reason in result.reasons
    )


@pytest.mark.django_db(transaction=True)
def test_private_offer_excludes_non_targets(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-5", password="pass")
    target = make_carrier(tenant=organization, email="target@example.com")
    outsider = make_carrier(tenant=organization, email="outsider@example.com")
    offer = published_offer(
        organization=organization,
        user=user,
        audience=FreightOfferAudience.PRIVATE,
        targets=[{"carrier": target}],
    )
    generate_match_candidates_for_offer(offer, actor=user)

    carrier_ids = set(
        get_current_match_candidates(offer)
        .exclude(carrier_id__isnull=True)
        .values_list("carrier_id", flat=True)
    )
    assert target.id in carrier_ids
    assert outsider.id not in carrier_ids


@pytest.mark.django_db(transaction=True)
def test_private_target_not_allowed_reason_for_outside_entity(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-6", password="pass")
    target = make_carrier(tenant=organization, email="only-target@example.com")
    outsider = make_carrier(tenant=organization, email="leak@example.com")
    offer = published_offer(
        organization=organization,
        user=user,
        audience=FreightOfferAudience.PRIVATE,
        targets=[{"carrier": target}],
    )

    target_carrier_ids, target_driver_ids = load_private_target_ids(offer)
    result = evaluate_private_target_access(
        offer=offer,
        carrier=outsider,
        driver=None,
        target_carrier_ids=target_carrier_ids,
        target_driver_ids=target_driver_ids,
    )
    assert result.status == MatchEligibilityStatus.INELIGIBLE
    assert any(
        reason.code == MatchEligibilityReasonCode.PRIVATE_TARGET_NOT_ALLOWED
        for reason in result.reasons
    )


@pytest.mark.django_db(transaction=True)
def test_refrigerated_vehicle_compatible_thermal_range(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-7", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(
        organization=organization,
        plate="FRG1A11",
        cargo_profile=VehicleCargoProfile.REFRIGERATED_CARGO,
        refrigerated=True,
    )
    upsert_refrigeration_profile(
        vehicle=vehicle,
        data=RefrigerationProfileData(
            temperature_min_c=Decimal("-10"),
            temperature_max_c=Decimal("10"),
        ),
    )
    assign_driver_to_vehicle(
        driver=driver,
        vehicle=vehicle,
        valid_from=date.today(),
    )
    offer = published_offer(
        organization=organization,
        user=user,
        audience=FreightOfferAudience.DRIVERS,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
    )
    generate_match_candidates_for_offer(offer, actor=user)
    candidate = get_current_match_candidates(offer).get(driver=driver, vehicle=vehicle)
    assert candidate.eligibility_status == MatchEligibilityStatus.ELIGIBLE.value
    assert candidate.temperature_score == Decimal("100.00")


@pytest.mark.django_db(transaction=True)
def test_refrigerated_vehicle_incompatible_thermal_range(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-8", password="pass")
    driver = active_driver(organization=organization, name="Driver Cold")
    vehicle = compliant_vehicle(
        organization=organization,
        plate="FRG2B22",
        cargo_profile=VehicleCargoProfile.REFRIGERATED_CARGO,
        refrigerated=True,
    )
    profile = upsert_refrigeration_profile(
        vehicle=vehicle,
        data=RefrigerationProfileData(
            temperature_min_c=Decimal("10"),
            temperature_max_c=Decimal("20"),
        ),
    )
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    offer = published_offer(
        organization=organization,
        user=user,
        audience=FreightOfferAudience.DRIVERS,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
    )

    result = evaluate_vehicle_eligibility(offer=offer, vehicle=vehicle, refrigeration=profile)
    assert result.status == MatchEligibilityStatus.INELIGIBLE
    assert any(
        reason.code == MatchEligibilityReasonCode.TEMPERATURE_RANGE_INCOMPATIBLE
        for reason in result.reasons
    )


@pytest.mark.django_db(transaction=True)
def test_non_refrigerated_vehicle_ineligible_for_refrigerated_offer(organization, django_user_model):
    user = django_user_model.objects.create_user(username="matcher-9", password="pass")
    driver = active_driver(organization=organization, name="Driver Dry")
    vehicle = compliant_vehicle(
        organization=organization,
        plate="DRY3C33",
        cargo_profile=VehicleCargoProfile.DRY_CARGO,
    )
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    offer = published_offer(
        organization=organization,
        user=user,
        audience=FreightOfferAudience.DRIVERS,
        cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO,
    )
    generate_match_candidates_for_offer(offer, actor=user)
    candidate = get_current_match_candidates(offer).get(driver=driver, vehicle=vehicle)
    assert candidate.eligibility_status == MatchEligibilityStatus.INELIGIBLE.value
    codes = {item["code"] for item in candidate.eligibility_reasons}
    assert MatchEligibilityReasonCode.CARGO_PROFILE_INCOMPATIBLE.value in codes


@pytest.mark.django_db(transaction=True)
def test_tenant_isolation_for_match_candidates(
    organization, other_organization, django_user_model, rbac_ready
):
    owner = django_user_model.objects.create_user(username="owner-match", password="pass")
    outsider = django_user_model.objects.create_user(username="outsider-match", password="pass")
    grant(owner, organization, RoleCode.DISPATCHER)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN)

    make_carrier(tenant=organization, email="tenant-carrier@example.com")
    offer = published_offer(organization=organization, user=owner)
    generate_match_candidates_for_offer(offer, actor=owner)
    candidate = get_current_match_candidates(offer).first()

    assert candidate in scoped_freight_match_candidate_queryset(
        owner, PermissionCode.FREIGHT_MATCHING_VIEW
    )
    assert candidate not in scoped_freight_match_candidate_queryset(
        outsider, PermissionCode.FREIGHT_MATCHING_VIEW
    )


@pytest.mark.django_db(transaction=True)
def test_salesperson_cannot_generate_matching(organization, django_user_model, rbac_ready):
    user = django_user_model.objects.create_user(username="sales-match", password="pass")
    grant(user, organization, RoleCode.SALESPERSON)
    assert not user_has_backoffice_permission(user, PermissionCode.FREIGHT_MATCHING_GENERATE)
    assert not user_has_backoffice_permission(user, PermissionCode.FREIGHT_MATCHING_INVITE)


@pytest.mark.django_db(transaction=True)
def test_dispatcher_can_generate_matching(organization, django_user_model, rbac_ready):
    user = django_user_model.objects.create_user(username="dispatch-match", password="pass")
    grant(user, organization, RoleCode.DISPATCHER)
    assert user_has_backoffice_permission(user, PermissionCode.FREIGHT_MATCHING_GENERATE)


@pytest.mark.django_db(transaction=True)
def test_invitation_creation_and_duplicate_guard(organization, django_user_model, rbac_ready):
    dispatcher = django_user_model.objects.create_user(username="invite-dispatch", password="pass")
    grant(dispatcher, organization, RoleCode.DISPATCHER)
    make_carrier(tenant=organization, email="invite-carrier@example.com")
    offer = published_offer(organization=organization, user=dispatcher)
    generate_match_candidates_for_offer(offer, actor=dispatcher)
    candidate = (
        get_current_match_candidates(offer)
        .filter(eligibility_status=MatchEligibilityStatus.ELIGIBLE.value)
        .first()
    )
    assert candidate is not None

    invitation = invite_match_candidate(candidate=candidate, actor=dispatcher)
    assert invitation.status == FreightOfferInvitationStatus.SENT.value
    assert invitation.match_candidate_id == candidate.id
    assert invitation.carrier_id == candidate.carrier_id
    assert MarketplaceEvent.objects.filter(
        offer=offer,
        event_type="offer_invited",
    ).exists()

    with pytest.raises(ValidationError):
        invite_match_candidate(candidate=candidate, actor=dispatcher)


@pytest.mark.django_db(transaction=True)
def test_invitation_cancel_and_decline_reason_field(organization, django_user_model, rbac_ready):
    dispatcher = django_user_model.objects.create_user(username="cancel-invite", password="pass")
    grant(dispatcher, organization, RoleCode.DISPATCHER)
    make_carrier(tenant=organization, email="cancel-carrier@example.com")
    offer = published_offer(organization=organization, user=dispatcher)
    generate_match_candidates_for_offer(offer, actor=dispatcher)
    candidate = get_current_match_candidates(offer).filter(
        eligibility_status=MatchEligibilityStatus.ELIGIBLE.value
    ).first()
    invitation = invite_match_candidate(candidate=candidate, actor=dispatcher)

    cancelled = cancel_freight_offer_invitation(invitation=invitation, actor=dispatcher)
    assert cancelled.status == FreightOfferInvitationStatus.CANCELLED.value
    assert AuditLog.objects.filter(action="freight_invitation_cancelled").exists()

    invitation.decline_reason = InvitationDeclineReason.TOO_FAR.value
    invitation.status = FreightOfferInvitationStatus.DECLINED.value
    invitation.full_clean()


@pytest.mark.django_db(transaction=True)
def test_scoped_invitation_queryset_respects_tenant(
    organization, other_organization, django_user_model, rbac_ready
):
    owner = django_user_model.objects.create_user(username="inv-owner", password="pass")
    outsider = django_user_model.objects.create_user(username="inv-outsider", password="pass")
    grant(owner, organization, RoleCode.DISPATCHER)
    grant(outsider, other_organization, RoleCode.COMPANY_ADMIN)

    make_carrier(tenant=organization, email="inv-carrier@example.com")
    offer = published_offer(organization=organization, user=owner)
    generate_match_candidates_for_offer(offer, actor=owner)
    candidate = get_current_match_candidates(offer).filter(
        eligibility_status=MatchEligibilityStatus.ELIGIBLE.value
    ).first()
    invitation = invite_match_candidate(candidate=candidate, actor=owner)

    assert invitation in scoped_freight_offer_invitation_queryset(
        owner, PermissionCode.FREIGHT_MATCHING_VIEW
    )
    assert invitation not in scoped_freight_offer_invitation_queryset(
        outsider, PermissionCode.FREIGHT_MATCHING_VIEW
    )


@pytest.mark.django_db(transaction=True)
def test_matching_not_available_for_draft_offer(organization, django_user_model):
    user = django_user_model.objects.create_user(username="draft-match", password="pass")
    customer = make_customer(organization)
    request, quote = ready_request_with_quote(organization=organization, user=user, customer=customer)
    offer = create_freight_offer(
        data=FreightOfferData(
            freight_request=request,
            freight_quote=quote,
            created_by=user,
            offer_amount=Decimal("3500"),
            audience=FreightOfferAudience.CARRIERS,
            expires_at=timezone.now() + timedelta(days=7),
        ),
        actor=user,
    )
    with pytest.raises(ValidationError):
        generate_match_candidates_for_offer(offer, actor=user)


@pytest.mark.django_db(transaction=True)
def test_drivers_audience_generates_driver_vehicle_candidates(organization, django_user_model):
    user = django_user_model.objects.create_user(username="drivers-aud", password="pass")
    driver = active_driver(organization=organization, compliant=True)
    vehicle = compliant_vehicle(organization=organization, plate="DRV4D44")
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    offer = published_offer(
        organization=organization,
        user=user,
        audience=FreightOfferAudience.DRIVERS,
    )
    generate_match_candidates_for_offer(offer, actor=user)
    assert get_current_match_candidates(offer).filter(driver=driver, vehicle=vehicle).exists()


@pytest.mark.django_db(transaction=True)
def test_ranking_is_deterministic_for_same_input(organization, django_user_model):
    user = django_user_model.objects.create_user(username="rank-det", password="pass")
    make_carrier(tenant=organization, email="rank1@example.com")
    make_carrier(tenant=organization, email="rank2@example.com")
    offer = published_offer(organization=organization, user=user)
    generate_match_candidates_for_offer(offer, actor=user, regenerate=False)
    first_order = list(
        get_current_match_candidates(offer).values_list("carrier_id", "rank_position")
    )
    generate_match_candidates_for_offer(offer, actor=user, regenerate=True)
    second_order = list(
        get_current_match_candidates(offer).values_list("carrier_id", "rank_position")
    )
    assert first_order == second_order
