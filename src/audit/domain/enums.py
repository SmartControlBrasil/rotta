from enum import StrEnum


class AuditAction(StrEnum):
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    MEMBERSHIP_CREATED = "membership_created"
    MEMBERSHIP_UPDATED = "membership_updated"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REMOVED = "role_removed"
