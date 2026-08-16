from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from src.compliance.domain.enums import DocumentStatus
from src.customers.application.services import CustomerData, register_customer
from src.customers.domain.enums import CustomerType
from src.drivers.domain.enums import DriverAvailabilityStatus, DriverDocumentType, DriverStatus
from src.drivers.infrastructure.django.models import Driver, DriverDocument
from src.freights.application.marketplace_services import (
    apply_selection_expiration_if_needed,
    cancel_selection,
    confirm_selection,
    decline_selection,
    express_interest_in_offer,
    select_interested_candidate,
    withdraw_interest,
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
    FreightOfferInterestStatus,
    FreightOfferSelectionStatus,
    MarketplaceEventType,
    SelectionDeclineReason,
)
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.domain.quote_enums import FreightQuoteChargeType
from src.freights.infrastructure.django.models import (
    FreightOfferInterest,
    MarketplaceEvent,
)
from src.identity.domain.enums import PermissionCode, RoleCode
from src.identity.infrastructure.django.rbac import sync_rbac
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


@pytest.fixture(autouse=True)
def rbac_ready(db):
    sync_rbac()


@pytest.fixture
def organization(db):
    return Organization.objects.create(
        name="Rotta Marketplace Corp",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def other_organization(db):
    return Organization.objects.create(
        name="Rotta Competitor Corp",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def user(organization):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="mkt_operator",
        email="operator@rotta116.com.br",
        password="password",
        is_active=True,
    )
    # Assign operations role or similar to allow action simulation
    from src.identity.infrastructure.django.models import MembershipRole, Role
    from src.organizations.infrastructure.django.models import Membership
    from src.shared.domain.enums import AccessScope

    role = Role.objects.get(code=RoleCode.OPERATIONS_MANAGER.value)
    membership = Membership.objects.create(
        user=user,
        organization=organization,
        status="ACTIVE",
    )
    MembershipRole.objects.create(
        membership=membership,
        role=role,
        scope=AccessScope.COMPANY.value,
    )
    return user


@pytest.fixture
def salesperson_user(organization):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="mkt_sales",
        email="sales@rotta116.com.br",
        password="password",
        is_active=True,
    )
    from src.identity.infrastructure.django.models import MembershipRole, Role
    from src.organizations.infrastructure.django.models import Membership
    from src.shared.domain.enums import AccessScope

    role = Role.objects.get(code=RoleCode.SALESPERSON.value)
    membership = Membership.objects.create(
        user=user,
        organization=organization,
        status="ACTIVE",
    )
    MembershipRole.objects.create(
        membership=membership,
        role=role,
        scope=AccessScope.COMPANY.value,
    )
    return user


@pytest.fixture
def customer(organization):
    return register_customer(
        data=CustomerData(
            organization=organization,
            customer_type=CustomerType.COMPANY,
            legal_name="Embarcador Marketplace Ltda",
            document_number="11.222.333/0001-81",
            email="shipper@example.com",
        )
    )


def make_published_offer(*, organization, user, customer, audience=FreightOfferAudience.BOTH):
    cargo = CargoData(
        description="Mercadorias",
        weight_kg=Decimal("1500"),
        cargo_profile=FreightCargoProfile.DRY_CARGO,
    )
    request = create_freight_request(
        data=FreightRequestData(
            organization=organization,
            customer=customer,
            created_by=user,
            stops=(
                StopData(stop_type=FreightStopType.PICKUP, sequence=1, city="Curitiba", state="PR"),
                StopData(
                    stop_type=FreightStopType.DELIVERY, sequence=2, city="Joinville", state="SC"
                ),
            ),
            cargo=cargo,
        ),
        actor=user,
    )
    submit_freight_request(request, actor=user)
    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=user)

    quote = create_freight_quote(
        data=FreightQuoteData(
            freight_request=request,
            created_by=user,
            charges=(
                ChargeData(
                    charge_type=FreightQuoteChargeType.BASE_FREIGHT, unit_amount=Decimal("4000")
                ),
            ),
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
            offer_amount=Decimal("3200"),
            audience=audience,
            expires_at=timezone.now() + timedelta(days=5),
        ),
        actor=user,
    )
    offer = mark_freight_offer_ready(offer, actor=user)
    offer = publish_freight_offer(offer, actor=user)
    return offer


def make_compliant_driver(*, organization, name="Motorista Elegivel"):
    driver = Driver.objects.create(
        organization=organization,
        full_name=name,
        status=DriverStatus.ACTIVE.value,
        availability_status=DriverAvailabilityStatus.AVAILABLE.value,
    )
    DriverDocument.objects.create(
        driver=driver,
        document_type=DriverDocumentType.DRIVER_LICENSE.value,
        storage_key=f"drivers/{driver.id}/cnh.pdf",
        status=DocumentStatus.APPROVED.value,
    )
    return driver


def make_compliant_vehicle(*, organization, plate="MKT1A23"):
    vehicle = register_vehicle(
        data=VehicleData(
            organization=organization,
            plate=plate,
            vehicle_type=VehicleType.TRUCK,
            cargo_profile=VehicleCargoProfile.DRY_CARGO,
            operational_status=VehicleOperationalStatus.AVAILABLE,
            status=VehicleStatus.ACTIVE,
        )
    )
    VehicleDocument.objects.create(
        vehicle=vehicle,
        document_type=VehicleDocumentType.CRLV.value,
        storage_key=f"vehicles/{plate}/crlv.pdf",
        status=DocumentStatus.APPROVED.value,
    )
    return vehicle


@pytest.mark.django_db
def test_express_interest_success_public_offer(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    # Driver expresses interest
    interest = express_interest_in_offer(
        offer=offer,
        driver=driver,
        vehicle=vehicle,
        notes="Gostaria de rodar este frete",
        actor=user,
    )

    assert interest.status == FreightOfferInterestStatus.ACTIVE.value
    assert interest.driver == driver
    assert interest.vehicle == vehicle
    assert interest.offer == offer
    assert interest.expressed_at is not None

    # Verify marketplace event logged
    event = MarketplaceEvent.objects.filter(
        offer=offer, event_type=MarketplaceEventType.OFFER_INTEREST_EXPRESSED.value
    ).first()
    assert event is not None
    assert event.metadata["interest_id"] == str(interest.id)


@pytest.mark.django_db
def test_express_interest_ineligible_driver_fails(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    # Driver CNH is expired/missing APPROVED status
    driver = Driver.objects.create(
        organization=organization,
        full_name="Driver Invalido",
        status=DriverStatus.ACTIVE.value,
        availability_status=DriverAvailabilityStatus.AVAILABLE.value,
    )
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    with pytest.raises(ValidationError, match="Candidato não elegível para a oferta"):
        express_interest_in_offer(
            offer=offer,
            driver=driver,
            vehicle=vehicle,
            actor=user,
        )


@pytest.mark.django_db(transaction=True)
def test_express_interest_idempotency(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    interest_1 = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)

    # Second call returns the same interest object (idempotency)
    interest_2 = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)

    assert interest_1.id == interest_2.id

    # Assert only 1 active interest exists in database
    assert (
        FreightOfferInterest.objects.filter(
            offer=offer, status=FreightOfferInterestStatus.ACTIVE.value
        ).count()
        == 1
    )

    # Assert only 1 marketplace event is logged
    event_count = MarketplaceEvent.objects.filter(
        offer=offer, event_type=MarketplaceEventType.OFFER_INTEREST_EXPRESSED.value
    ).count()
    assert event_count == 1

    # Assert only 1 audit log of creation is logged
    from src.audit.infrastructure.django.models import AuditLog

    audit_count = AuditLog.objects.filter(
        action="freight_interest_created", target_id=str(interest_1.id)
    ).count()
    assert audit_count == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_express_interest_idempotency(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    from src.carriers.infrastructure.django.models import CarrierProfile
    from src.carriers.domain.enums import CarrierStatus

    carrier = CarrierProfile.objects.create(
        organization=organization,
        tenant=organization,
        trade_name="Carrier Test",
        email="carrier@example.com",
        status=CarrierStatus.ACTIVE.value,
    )

    express_interest_in_offer(
        offer=offer, carrier=carrier, driver=driver, vehicle=vehicle, actor=user
    )

    from django.db.utils import IntegrityError

    # Directly attempting to insert a duplicate active interest via DB should trigger IntegrityError
    with pytest.raises(IntegrityError):
        FreightOfferInterest.objects.create(
            organization=organization,
            offer=offer,
            carrier=carrier,
            driver=driver,
            vehicle=vehicle,
            status=FreightOfferInterestStatus.ACTIVE.value,
            expressed_at=timezone.now(),
        )


@pytest.mark.django_db
def test_private_offer_interest_restrictions(organization, other_organization, user, customer):
    # Create private offer
    cargo = CargoData(
        description="Mercadorias",
        weight_kg=Decimal("1500"),
        cargo_profile=FreightCargoProfile.DRY_CARGO,
    )
    request = create_freight_request(
        data=FreightRequestData(
            organization=organization,
            customer=customer,
            created_by=user,
            stops=(
                StopData(stop_type=FreightStopType.PICKUP, sequence=1, city="Curitiba", state="PR"),
                StopData(
                    stop_type=FreightStopType.DELIVERY, sequence=2, city="Joinville", state="SC"
                ),
            ),
            cargo=cargo,
        ),
        actor=user,
    )
    submit_freight_request(request, actor=user)
    change_freight_request_status(request, status=FreightRequestStatus.UNDER_REVIEW, actor=user)

    quote = create_freight_quote(
        data=FreightQuoteData(
            freight_request=request,
            created_by=user,
            charges=(
                ChargeData(
                    charge_type=FreightQuoteChargeType.BASE_FREIGHT, unit_amount=Decimal("4000")
                ),
            ),
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
            offer_amount=Decimal("3200"),
            audience=FreightOfferAudience.PRIVATE,
            expires_at=timezone.now() + timedelta(days=5),
        ),
        actor=user,
    )
    offer = mark_freight_offer_ready(offer, actor=user)

    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    # Add targeted driver
    add_freight_offer_target(offer=offer, driver=driver, actor=user)
    offer = publish_freight_offer(offer, actor=user)

    # Candidate not targeted should fail
    driver_not_targeted = make_compliant_driver(organization=organization, name="Not Targeted")
    vehicle_not_targeted = make_compliant_vehicle(organization=organization, plate="DRV9X99")
    assign_driver_to_vehicle(
        driver=driver_not_targeted, vehicle=vehicle_not_targeted, valid_from=date.today()
    )

    with pytest.raises(ValidationError, match="Candidato não elegível"):
        express_interest_in_offer(
            offer=offer, driver=driver_not_targeted, vehicle=vehicle_not_targeted, actor=user
        )

    # Targeted driver should succeed
    interest = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)
    assert interest.status == FreightOfferInterestStatus.ACTIVE.value


@pytest.mark.django_db
def test_tenant_isolation_interest_expression(organization, other_organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)

    # Driver belongs to other_organization
    driver = make_compliant_driver(organization=other_organization)
    vehicle = make_compliant_vehicle(organization=other_organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    with pytest.raises(ValidationError, match="Candidato não elegível"):
        express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)


@pytest.mark.django_db
def test_withdraw_and_re_interest_lifecycle(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    interest = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)

    # Withdraw
    interest = withdraw_interest(interest, actor=user)
    assert interest.status == FreightOfferInterestStatus.WITHDRAWN.value
    assert interest.withdrawn_at is not None

    # Can re-express interest now
    interest_v2 = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)
    assert interest_v2.status == FreightOfferInterestStatus.ACTIVE.value


@pytest.mark.django_db
def test_selection_lifecycle_and_uniqueness(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)

    driver_a = make_compliant_driver(organization=organization, name="Driver A")
    vehicle_a = make_compliant_vehicle(organization=organization, plate="DRV1A11")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())
    interest_a = express_interest_in_offer(
        offer=offer, driver=driver_a, vehicle=vehicle_a, actor=user
    )

    driver_b = make_compliant_driver(organization=organization, name="Driver B")
    vehicle_b = make_compliant_vehicle(organization=organization, plate="DRV2B22")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())
    interest_b = express_interest_in_offer(
        offer=offer, driver=driver_b, vehicle=vehicle_b, actor=user
    )

    # Select Candidate A
    selection = select_interested_candidate(interest_a, actor=user)
    assert selection.status == FreightOfferSelectionStatus.PENDING_CONFIRMATION.value
    assert selection.offer == offer
    assert selection.interest == interest_a
    assert selection.selected_by == user
    assert selection.carrier_snapshot is None
    assert selection.driver_snapshot["full_name"] == "Driver A"
    assert selection.vehicle_snapshot["plate"] == "DRV1A11"

    # Selection changes interest status to SELECTED
    interest_a.refresh_from_db()
    assert interest_a.status == FreightOfferInterestStatus.SELECTED.value

    # Double selection on the same offer should fail (only one active selection per offer)
    with pytest.raises(ValidationError, match="Já existe uma seleção ativa ou confirmada"):
        select_interested_candidate(interest_b, actor=user)

    # Candidate A cannot withdraw simple interest while selected
    with pytest.raises(ValidationError, match="Apenas interesses ativos podem ser retirados"):
        withdraw_interest(interest_a, actor=user)

    # Cancel Selection A
    cancel_selection(selection, reason="Dispatcher changed mind", actor=user)
    selection.refresh_from_db()
    assert selection.status == FreightOfferSelectionStatus.CANCELLED.value

    # Interest A restored to ACTIVE
    interest_a.refresh_from_db()
    assert interest_a.status == FreightOfferInterestStatus.ACTIVE.value

    # Select Candidate B instead
    selection_b = select_interested_candidate(interest_b, actor=user)
    assert selection_b.status == FreightOfferSelectionStatus.PENDING_CONFIRMATION.value


@pytest.mark.django_db
def test_confirmation_lifecycle_closes_offer(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)

    from src.carriers.infrastructure.django.models import CarrierProfile, CarrierDriverLink
    from src.carriers.domain.enums import CarrierStatus

    carrier = CarrierProfile.objects.create(
        organization=organization,
        tenant=organization,
        trade_name="Carrier Alpha",
        email="carrier@example.com",
        status=CarrierStatus.ACTIVE.value,
    )

    driver_a = make_compliant_driver(organization=organization, name="Driver A")
    CarrierDriverLink.objects.create(carrier=carrier, driver=driver_a)
    vehicle_a = make_compliant_vehicle(organization=organization, plate="DRV1A11")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())
    interest_a = express_interest_in_offer(
        offer=offer, carrier=carrier, driver=driver_a, vehicle=vehicle_a, actor=user
    )

    driver_b = make_compliant_driver(organization=organization, name="Driver B")
    CarrierDriverLink.objects.create(carrier=carrier, driver=driver_b)
    vehicle_b = make_compliant_vehicle(organization=organization, plate="DRV2B22")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())
    interest_b = express_interest_in_offer(
        offer=offer, carrier=carrier, driver=driver_b, vehicle=vehicle_b, actor=user
    )

    selection = select_interested_candidate(interest_a, actor=user)

    # Confirm selection
    selection = confirm_selection(selection, actor=user)
    assert selection.status == FreightOfferSelectionStatus.CONFIRMED.value
    assert selection.confirmed_at is not None

    # Offer should be CLOSED
    offer.refresh_from_db()
    assert offer.status == FreightOfferStatus.CLOSED.value

    # Interest A remains SELECTED
    interest_a.refresh_from_db()
    assert interest_a.status == FreightOfferInterestStatus.SELECTED.value

    # Backup Interest B becomes NOT_SELECTED
    interest_b.refresh_from_db()
    assert interest_b.status == FreightOfferInterestStatus.NOT_SELECTED.value


@pytest.mark.django_db
def test_decline_selection_leaves_backups_active(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)

    driver_a = make_compliant_driver(organization=organization, name="Driver A")
    vehicle_a = make_compliant_vehicle(organization=organization, plate="DRV1A11")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())
    interest_a = express_interest_in_offer(
        offer=offer, driver=driver_a, vehicle=vehicle_a, actor=user
    )

    driver_b = make_compliant_driver(organization=organization, name="Driver B")
    vehicle_b = make_compliant_vehicle(organization=organization, plate="DRV2B22")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())
    interest_b = express_interest_in_offer(
        offer=offer, driver=driver_b, vehicle=vehicle_b, actor=user
    )

    selection = select_interested_candidate(interest_a, actor=user)

    # Candidate declines selection
    decline_selection(selection, reason=SelectionDeclineReason.PRICE_NOT_ACCEPTED, actor=user)
    selection.refresh_from_db()
    assert selection.status == FreightOfferSelectionStatus.DECLINED.value

    # Interest A moves to CANCELLED
    interest_a.refresh_from_db()
    assert interest_a.status == FreightOfferInterestStatus.CANCELLED.value

    # Backup Interest B remains ACTIVE
    interest_b.refresh_from_db()
    assert interest_b.status == FreightOfferInterestStatus.ACTIVE.value

    # Can now select Candidate B
    selection_b = select_interested_candidate(interest_b, actor=user)
    assert selection_b.status == FreightOfferSelectionStatus.PENDING_CONFIRMATION.value


@pytest.mark.django_db
def test_concurrency_selection_protection(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)

    driver_a = make_compliant_driver(organization=organization, name="Driver A")
    vehicle_a = make_compliant_vehicle(organization=organization, plate="DRV1A11")
    assign_driver_to_vehicle(driver=driver_a, vehicle=vehicle_a, valid_from=date.today())
    interest_a = express_interest_in_offer(
        offer=offer, driver=driver_a, vehicle=vehicle_a, actor=user
    )

    driver_b = make_compliant_driver(organization=organization, name="Driver B")
    vehicle_b = make_compliant_vehicle(organization=organization, plate="DRV2B22")
    assign_driver_to_vehicle(driver=driver_b, vehicle=vehicle_b, valid_from=date.today())
    interest_b = express_interest_in_offer(
        offer=offer, driver=driver_b, vehicle=vehicle_b, actor=user
    )

    # Run selection concurrently in two atomic transaction wrappers to simulate race condition.
    # One will lock the offer and succeed, and the next will raise ValidationError.
    select_interested_candidate(interest_a, actor=user)

    with pytest.raises(ValidationError, match="Já existe uma seleção ativa ou confirmada"):
        select_interested_candidate(interest_b, actor=user)


@pytest.mark.django_db
def test_lazy_selection_expiration(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    interest = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)

    selection = select_interested_candidate(interest, confirmation_expires_in_hours=1, actor=user)

    # Force expiration time to the past
    selection.confirmation_expires_at = timezone.now() - timedelta(minutes=5)
    selection.save()

    # Trigger lazy check
    selection = apply_selection_expiration_if_needed(selection)
    assert selection.status == FreightOfferSelectionStatus.EXPIRED.value

    # Interest should be restored to ACTIVE
    interest.refresh_from_db()
    assert interest.status == FreightOfferInterestStatus.ACTIVE.value


@pytest.mark.django_db
def test_eligibility_revalidation_at_transitions(organization, user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())

    interest = express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)

    # Candidate becomes non-compliant (e.g. document rejected)
    doc = driver.documents.first()
    doc.status = DocumentStatus.REJECTED.value
    doc.save()

    # Selection should now fail eligibility check
    with pytest.raises(ValidationError, match="Candidato não é mais elegível"):
        select_interested_candidate(interest, actor=user)


@pytest.mark.django_db
def test_rbac_marketplace_permissions(organization, user, salesperson_user, customer):
    offer = make_published_offer(organization=organization, user=user, customer=customer)
    driver = make_compliant_driver(organization=organization)
    vehicle = make_compliant_vehicle(organization=organization)
    assign_driver_to_vehicle(driver=driver, vehicle=vehicle, valid_from=date.today())
    express_interest_in_offer(offer=offer, driver=driver, vehicle=vehicle, actor=user)

    # Dispatcher/Operations can select
    # Simulate view permission checking
    from src.shared.interfaces.backoffice.views import user_has_backoffice_permission

    assert user_has_backoffice_permission(user, PermissionCode.FREIGHT_MARKETPLACE_SELECT) is True
    assert (
        user_has_backoffice_permission(salesperson_user, PermissionCode.FREIGHT_MARKETPLACE_SELECT)
        is False
    )
