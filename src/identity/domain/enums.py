from enum import StrEnum


class RoleCode(StrEnum):
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    OPERATIONS_MANAGER = "OPERATIONS_MANAGER"
    DISPATCHER = "DISPATCHER"
    FINANCIAL_MANAGER = "FINANCIAL_MANAGER"
    FINANCIAL_ANALYST = "FINANCIAL_ANALYST"
    COMMERCIAL_MANAGER = "COMMERCIAL_MANAGER"
    SALESPERSON = "SALESPERSON"
    DRIVER = "DRIVER"
    CUSTOMER = "CUSTOMER"
    AUDITOR = "AUDITOR"
    VIEWER = "VIEWER"


class PermissionCode(StrEnum):
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_UPDATE = "users.update"
    ORGANIZATIONS_VIEW = "organizations.view"
    ORGANIZATIONS_MANAGE = "organizations.manage"
    MEMBERSHIPS_VIEW = "memberships.view"
    MEMBERSHIPS_MANAGE = "memberships.manage"
    ROLES_MANAGE = "roles.manage"
    AUDIT_VIEW = "audit.view"
