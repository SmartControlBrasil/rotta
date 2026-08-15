from dataclasses import dataclass

from src.identity.domain.enums import PermissionCode, RoleCode


@dataclass(frozen=True)
class PermissionDefinition:
    code: PermissionCode
    name: str
    description: str = ""


@dataclass(frozen=True)
class RoleDefinition:
    code: RoleCode
    name: str
    description: str = ""


PERMISSIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition(PermissionCode.USERS_VIEW, "View users"),
    PermissionDefinition(PermissionCode.USERS_CREATE, "Create users"),
    PermissionDefinition(PermissionCode.USERS_UPDATE, "Update users"),
    PermissionDefinition(PermissionCode.ORGANIZATIONS_VIEW, "View organizations"),
    PermissionDefinition(PermissionCode.ORGANIZATIONS_MANAGE, "Manage organizations"),
    PermissionDefinition(PermissionCode.MEMBERSHIPS_VIEW, "View memberships"),
    PermissionDefinition(PermissionCode.MEMBERSHIPS_MANAGE, "Manage memberships"),
    PermissionDefinition(PermissionCode.ROLES_MANAGE, "Manage roles"),
    PermissionDefinition(PermissionCode.AUDIT_VIEW, "View audit logs"),
)

ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(RoleCode.SYSTEM_ADMIN, "System admin"),
    RoleDefinition(RoleCode.COMPANY_ADMIN, "Company admin"),
    RoleDefinition(RoleCode.OPERATIONS_MANAGER, "Operations manager"),
    RoleDefinition(RoleCode.DISPATCHER, "Dispatcher"),
    RoleDefinition(RoleCode.FINANCIAL_MANAGER, "Financial manager"),
    RoleDefinition(RoleCode.FINANCIAL_ANALYST, "Financial analyst"),
    RoleDefinition(RoleCode.COMMERCIAL_MANAGER, "Commercial manager"),
    RoleDefinition(RoleCode.SALESPERSON, "Salesperson"),
    RoleDefinition(RoleCode.DRIVER, "Driver"),
    RoleDefinition(RoleCode.CUSTOMER, "Customer"),
    RoleDefinition(RoleCode.AUDITOR, "Auditor"),
    RoleDefinition(RoleCode.VIEWER, "Viewer"),
)

ROLE_PERMISSIONS: dict[RoleCode, tuple[PermissionCode, ...]] = {
    RoleCode.SYSTEM_ADMIN: tuple(permission.code for permission in PERMISSIONS),
    RoleCode.COMPANY_ADMIN: (
        PermissionCode.USERS_VIEW,
        PermissionCode.USERS_CREATE,
        PermissionCode.USERS_UPDATE,
        PermissionCode.ORGANIZATIONS_VIEW,
        PermissionCode.ORGANIZATIONS_MANAGE,
        PermissionCode.MEMBERSHIPS_VIEW,
        PermissionCode.MEMBERSHIPS_MANAGE,
        PermissionCode.ROLES_MANAGE,
        PermissionCode.AUDIT_VIEW,
    ),
    RoleCode.OPERATIONS_MANAGER: (
        PermissionCode.USERS_VIEW,
        PermissionCode.ORGANIZATIONS_VIEW,
        PermissionCode.MEMBERSHIPS_VIEW,
    ),
    RoleCode.AUDITOR: (
        PermissionCode.AUDIT_VIEW,
        PermissionCode.ORGANIZATIONS_VIEW,
        PermissionCode.MEMBERSHIPS_VIEW,
    ),
    RoleCode.VIEWER: (
        PermissionCode.ORGANIZATIONS_VIEW,
        PermissionCode.MEMBERSHIPS_VIEW,
    ),
}
