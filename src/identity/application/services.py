from src.shared.domain.enums import AccessScope


def membership_has_permission(membership, permission_code: str) -> bool:
    return membership.roles.filter(permissions__code=permission_code).exists()


def membership_scope_for_permission(membership, permission_code: str) -> AccessScope:
    assignment = (
        membership.membership_roles.filter(role__permissions__code=permission_code)
        .order_by("scope")
        .first()
    )
    if assignment is None:
        return AccessScope.NONE
    return AccessScope(assignment.scope)
