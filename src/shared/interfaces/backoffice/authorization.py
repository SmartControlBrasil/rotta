from dataclasses import dataclass

from django.db.models import QuerySet

from src.identity.application.services import membership_scope_for_permission
from src.organizations.domain.enums import MembershipStatus
from src.organizations.infrastructure.django.models import Membership, Organization
from src.shared.domain.enums import AccessScope

_SCOPE_RANK = {
    AccessScope.NONE: 0,
    AccessScope.OWN: 1,
    AccessScope.TEAM: 2,
    AccessScope.DEPARTMENT: 3,
    AccessScope.BRANCH: 4,
    AccessScope.COMPANY: 5,
    AccessScope.ALL: 6,
}


@dataclass(frozen=True)
class PermissionGrant:
    allowed: bool
    scope: AccessScope = AccessScope.NONE
    memberships: tuple[Membership, ...] = ()


def active_memberships_for(user, permission_code: str) -> QuerySet[Membership]:
    return (
        Membership.objects.filter(
            user=user,
            status=MembershipStatus.ACTIVE,
            membership_roles__role__permissions__code=permission_code,
        )
        .select_related("organization", "business_unit", "branch", "department", "team", "user")
        .prefetch_related("membership_roles__role__permissions")
        .distinct()
    )


def permission_grant_for(user, permission_code: str) -> PermissionGrant:
    if not user.is_authenticated:
        return PermissionGrant(False)
    if user.is_superuser:
        return PermissionGrant(True, AccessScope.ALL)

    memberships = tuple(active_memberships_for(user, permission_code))
    if not memberships:
        return PermissionGrant(False)

    strongest_scope = AccessScope.NONE
    for membership in memberships:
        scope = membership_scope_for_permission(membership, permission_code)
        if _SCOPE_RANK[scope] > _SCOPE_RANK[strongest_scope]:
            strongest_scope = scope

    return PermissionGrant(strongest_scope != AccessScope.NONE, strongest_scope, memberships)


def user_has_backoffice_permission(user, permission_code: str) -> bool:
    return permission_grant_for(user, permission_code).allowed


def scoped_organization_queryset(user, permission_code: str):
    grant = permission_grant_for(user, permission_code)
    queryset = Organization.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(id__in=organization_ids)


def scoped_membership_queryset(user, permission_code: str):
    from src.organizations.infrastructure.django.models import Membership

    grant = permission_grant_for(user, permission_code)
    queryset = Membership.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(user=user)

    filters = {}
    for membership in grant.memberships:
        if grant.scope == AccessScope.TEAM and membership.team_id:
            filters.setdefault("team_id__in", set()).add(membership.team_id)
        elif grant.scope == AccessScope.DEPARTMENT and membership.department_id:
            filters.setdefault("department_id__in", set()).add(membership.department_id)
        elif grant.scope == AccessScope.BRANCH and membership.branch_id:
            filters.setdefault("branch_id__in", set()).add(membership.branch_id)
        else:
            filters.setdefault("organization_id__in", set()).add(membership.organization_id)

    normalized = {key: list(value) for key, value in filters.items()}
    if not normalized:
        return queryset.none()

    from django.db.models import Q

    condition = Q()
    for key, value in normalized.items():
        condition |= Q(**{key: value})
    return queryset.filter(condition)


def scoped_user_queryset(user, permission_code: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    memberships = scoped_membership_queryset(user, permission_code)
    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return User.objects.none()
    if grant.scope == AccessScope.ALL:
        return User.objects.all()
    if grant.scope == AccessScope.OWN:
        return User.objects.filter(id=user.id)
    return User.objects.filter(memberships__in=memberships).distinct()


def scoped_driver_queryset(user, permission_code: str):
    from src.drivers.infrastructure.django.models import Driver

    grant = permission_grant_for(user, permission_code)
    queryset = Driver.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(user=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_vehicle_queryset(user, permission_code: str):
    from src.vehicles.infrastructure.django.models import Vehicle

    grant = permission_grant_for(user, permission_code)
    queryset = Vehicle.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(driver_assignments__driver__user=user).distinct()

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_customer_queryset(user, permission_code: str):
    from src.customers.infrastructure.django.models import Customer

    grant = permission_grant_for(user, permission_code)
    queryset = Customer.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_carrier_queryset(user, permission_code: str):
    from src.carriers.infrastructure.django.models import CarrierProfile

    grant = permission_grant_for(user, permission_code)
    queryset = CarrierProfile.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(tenant_id__in=organization_ids)


def scoped_freight_request_queryset(user, permission_code: str):
    from src.freights.infrastructure.django.models import FreightRequest

    grant = permission_grant_for(user, permission_code)
    queryset = FreightRequest.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_freight_quote_queryset(user, permission_code: str):
    from src.freights.infrastructure.django.models import FreightQuote
    from src.identity.domain.enums import PermissionCode

    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return FreightQuote.objects.none()

    request_qs = scoped_freight_request_queryset(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
    queryset = FreightQuote.objects.filter(freight_request__in=request_qs)
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_freight_offer_queryset(user, permission_code: str):
    from src.freights.infrastructure.django.models import FreightOffer
    from src.identity.domain.enums import PermissionCode

    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return FreightOffer.objects.none()

    request_qs = scoped_freight_request_queryset(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
    queryset = FreightOffer.objects.filter(freight_request__in=request_qs)
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_freight_match_candidate_queryset(user, permission_code: str):
    from src.freights.infrastructure.django.models import FreightMatchCandidate
    from src.identity.domain.enums import PermissionCode

    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return FreightMatchCandidate.objects.none()

    offer_qs = scoped_freight_offer_queryset(user, PermissionCode.FREIGHT_OFFERS_VIEW)
    queryset = FreightMatchCandidate.objects.filter(offer__in=offer_qs)
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(offer__owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_freight_offer_invitation_queryset(user, permission_code: str):
    from src.freights.infrastructure.django.models import FreightOfferInvitation
    from src.identity.domain.enums import PermissionCode

    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return FreightOfferInvitation.objects.none()

    offer_qs = scoped_freight_offer_queryset(user, PermissionCode.FREIGHT_OFFERS_VIEW)
    queryset = FreightOfferInvitation.objects.filter(offer__in=offer_qs)
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(offer__owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_driver_route_intent_queryset(user, permission_code: str):
    from src.drivers.infrastructure.django.models import DriverRouteIntent
    from src.identity.domain.enums import PermissionCode

    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return DriverRouteIntent.objects.none()

    driver_qs = scoped_driver_queryset(user, PermissionCode.DRIVERS_VIEW)
    queryset = DriverRouteIntent.objects.filter(driver__in=driver_qs)
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(driver__user=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_driver_document_queryset(user, permission_code: str):
    from src.drivers.infrastructure.django.models import DriverDocument
    from src.identity.domain.enums import PermissionCode

    drivers_qs = scoped_driver_queryset(user, PermissionCode.DRIVERS_VIEW)
    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return DriverDocument.objects.none()
    return DriverDocument.objects.filter(driver__in=drivers_qs)


def scoped_vehicle_document_queryset(user, permission_code: str):
    from src.identity.domain.enums import PermissionCode
    from src.vehicles.infrastructure.django.models import VehicleDocument

    vehicles_qs = scoped_vehicle_queryset(user, PermissionCode.VEHICLES_VIEW)
    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return VehicleDocument.objects.none()
    return VehicleDocument.objects.filter(vehicle__in=vehicles_qs)


def scoped_carrier_document_queryset(user, permission_code: str):
    from src.carriers.infrastructure.django.models import CarrierDocument
    from src.identity.domain.enums import PermissionCode

    carriers_qs = scoped_carrier_queryset(user, PermissionCode.CARRIERS_VIEW)
    grant = permission_grant_for(user, permission_code)
    if not grant.allowed:
        return CarrierDocument.objects.none()
    return CarrierDocument.objects.filter(carrier__in=carriers_qs)


def user_can_access_document(user, document, entity_type) -> bool:
    from src.compliance.domain.enums import EntityType
    from src.identity.domain.enums import PermissionCode

    if entity_type == EntityType.DRIVER:
        return (
            scoped_driver_document_queryset(user, PermissionCode.DOCUMENTS_VIEW)
            .filter(pk=document.pk)
            .exists()
        )
    if entity_type == EntityType.VEHICLE:
        return (
            scoped_vehicle_document_queryset(user, PermissionCode.DOCUMENTS_VIEW)
            .filter(pk=document.pk)
            .exists()
        )
    if entity_type == EntityType.CARRIER:
        return (
            scoped_carrier_document_queryset(user, PermissionCode.DOCUMENTS_VIEW)
            .filter(pk=document.pk)
            .exists()
        )
    return False


def scoped_business_unit_queryset(user, permission_code: str):
    from src.organizations.infrastructure.django.models import BusinessUnit

    grant = permission_grant_for(user, permission_code)
    queryset = BusinessUnit.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_branch_queryset(user, permission_code: str):
    from src.organizations.infrastructure.django.models import Branch

    grant = permission_grant_for(user, permission_code)
    queryset = Branch.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_department_queryset(user, permission_code: str):
    from src.organizations.infrastructure.django.models import Department

    grant = permission_grant_for(user, permission_code)
    queryset = Department.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_team_queryset(user, permission_code: str):
    from src.organizations.infrastructure.django.models import Team

    grant = permission_grant_for(user, permission_code)
    queryset = Team.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_freight_operations_queryset(user, permission_code: str) -> QuerySet:
    from src.freights.infrastructure.django.models import FreightOperation

    grant = permission_grant_for(user, permission_code)
    queryset = FreightOperation.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(selection__offer__owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(organization_id__in=organization_ids)


def scoped_freight_request_cargo_queryset(user, permission_code: str) -> QuerySet:
    from src.freights.infrastructure.django.models import FreightRequestCargo

    grant = permission_grant_for(user, permission_code)
    queryset = FreightRequestCargo.objects.all()
    if not grant.allowed:
        return queryset.none()
    if grant.scope == AccessScope.ALL:
        return queryset
    if grant.scope == AccessScope.OWN:
        return queryset.filter(freight_request__owner=user)

    organization_ids = {membership.organization_id for membership in grant.memberships}
    return queryset.filter(freight_request__organization_id__in=organization_ids)


