from enum import StrEnum


class AccessScope(StrEnum):
    ALL = "ALL"
    COMPANY = "COMPANY"
    BRANCH = "BRANCH"
    DEPARTMENT = "DEPARTMENT"
    TEAM = "TEAM"
    OWN = "OWN"
    NONE = "NONE"
