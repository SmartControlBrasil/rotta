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
