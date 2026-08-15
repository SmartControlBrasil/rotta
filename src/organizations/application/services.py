from django.core.exceptions import ValidationError
from django.db import transaction

from src.audit.infrastructure.django.services import record_audit_event
from src.organizations.infrastructure.django.models import (
    Branch,
    BusinessUnit,
    Department,
    Organization,
    Team,
)


@transaction.atomic
def create_organization(
    *, name, legal_name="", document="", type, is_active=True, actor=None
) -> Organization:
    org = Organization.objects.create(
        name=name,
        legal_name=legal_name,
        document=document,
        type=type,
        is_active=is_active,
    )
    record_audit_event(
        actor=actor,
        action="organization_created",
        target=org,
        organization=org,
        before={},
        after={
            "id": str(org.id),
            "name": org.name,
            "legal_name": org.legal_name,
            "document": org.document,
            "type": org.type,
            "is_active": org.is_active,
        },
    )
    return org


@transaction.atomic
def update_organization(
    org: Organization, *, name, legal_name, document, type, is_active, actor=None
) -> Organization:
    before = {
        "id": str(org.id),
        "name": org.name,
        "legal_name": org.legal_name,
        "document": org.document,
        "type": org.type,
        "is_active": org.is_active,
    }
    org.name = name
    org.legal_name = legal_name
    org.document = document
    org.type = type
    org.is_active = is_active
    org.save()
    after = {
        "id": str(org.id),
        "name": org.name,
        "legal_name": org.legal_name,
        "document": org.document,
        "type": org.type,
        "is_active": org.is_active,
    }
    record_audit_event(
        actor=actor,
        action="organization_updated",
        target=org,
        organization=org,
        before=before,
        after=after,
    )
    return org


@transaction.atomic
def create_business_unit(*, organization, name, is_active=True, actor=None) -> BusinessUnit:
    bu = BusinessUnit.objects.create(
        organization=organization,
        name=name,
        is_active=is_active,
    )
    record_audit_event(
        actor=actor,
        action="business_unit_created",
        target=bu,
        organization=organization,
        before={},
        after={
            "id": str(bu.id),
            "organization_id": str(organization.id),
            "name": bu.name,
            "is_active": bu.is_active,
        },
    )
    return bu


@transaction.atomic
def update_business_unit(bu: BusinessUnit, *, name, is_active, actor=None) -> BusinessUnit:
    before = {
        "id": str(bu.id),
        "organization_id": str(bu.organization.id),
        "name": bu.name,
        "is_active": bu.is_active,
    }
    bu.name = name
    bu.is_active = is_active
    bu.save()
    after = {
        "id": str(bu.id),
        "organization_id": str(bu.organization.id),
        "name": bu.name,
        "is_active": bu.is_active,
    }
    record_audit_event(
        actor=actor,
        action="business_unit_updated",
        target=bu,
        organization=bu.organization,
        before=before,
        after=after,
    )
    return bu


@transaction.atomic
def create_branch(
    *, organization, business_unit=None, name, code="", is_active=True, actor=None
) -> Branch:
    if business_unit and business_unit.organization != organization:
        raise ValidationError(
            {
                "business_unit": (
                    "A Unidade de Negócio selecionada deve pertencer à mesma Organização."
                )
            }
        )
    branch = Branch.objects.create(
        organization=organization,
        business_unit=business_unit,
        name=name,
        code=code,
        is_active=is_active,
    )
    record_audit_event(
        actor=actor,
        action="branch_created",
        target=branch,
        organization=organization,
        before={},
        after={
            "id": str(branch.id),
            "organization_id": str(organization.id),
            "business_unit_id": str(business_unit.id) if business_unit else None,
            "name": branch.name,
            "code": branch.code,
            "is_active": branch.is_active,
        },
    )
    return branch


@transaction.atomic
def update_branch(
    branch: Branch, *, business_unit=None, name, code, is_active, actor=None
) -> Branch:
    if business_unit and business_unit.organization != branch.organization:
        raise ValidationError(
            {
                "business_unit": (
                    "A Unidade de Negócio selecionada deve pertencer à mesma Organização."
                )
            }
        )
    before = {
        "id": str(branch.id),
        "organization_id": str(branch.organization.id),
        "business_unit_id": str(branch.business_unit.id) if branch.business_unit else None,
        "name": branch.name,
        "code": branch.code,
        "is_active": branch.is_active,
    }
    branch.business_unit = business_unit
    branch.name = name
    branch.code = code
    branch.is_active = is_active
    branch.save()
    after = {
        "id": str(branch.id),
        "organization_id": str(branch.organization.id),
        "business_unit_id": str(branch.business_unit.id) if branch.business_unit else None,
        "name": branch.name,
        "code": branch.code,
        "is_active": branch.is_active,
    }
    record_audit_event(
        actor=actor,
        action="branch_updated",
        target=branch,
        organization=branch.organization,
        before=before,
        after=after,
    )
    return branch


@transaction.atomic
def create_department(*, organization, branch=None, name, is_active=True, actor=None) -> Department:
    if branch and branch.organization != organization:
        raise ValidationError(
            {"branch": "A Filial selecionada deve pertencer à mesma Organização."}
        )
    dept = Department.objects.create(
        organization=organization,
        branch=branch,
        name=name,
        is_active=is_active,
    )
    record_audit_event(
        actor=actor,
        action="department_created",
        target=dept,
        organization=organization,
        before={},
        after={
            "id": str(dept.id),
            "organization_id": str(organization.id),
            "branch_id": str(branch.id) if branch else None,
            "name": dept.name,
            "is_active": dept.is_active,
        },
    )
    return dept


@transaction.atomic
def update_department(dept: Department, *, branch=None, name, is_active, actor=None) -> Department:
    if branch and branch.organization != dept.organization:
        raise ValidationError(
            {"branch": "A Filial selecionada deve pertencer à mesma Organização."}
        )
    before = {
        "id": str(dept.id),
        "organization_id": str(dept.organization.id),
        "branch_id": str(dept.branch.id) if dept.branch else None,
        "name": dept.name,
        "is_active": dept.is_active,
    }
    dept.branch = branch
    dept.name = name
    dept.is_active = is_active
    dept.save()
    after = {
        "id": str(dept.id),
        "organization_id": str(dept.organization.id),
        "branch_id": str(dept.branch.id) if dept.branch else None,
        "name": dept.name,
        "is_active": dept.is_active,
    }
    record_audit_event(
        actor=actor,
        action="department_updated",
        target=dept,
        organization=dept.organization,
        before=before,
        after=after,
    )
    return dept


@transaction.atomic
def create_team(*, organization, department=None, name, is_active=True, actor=None) -> Team:
    if department and department.organization != organization:
        raise ValidationError(
            {"department": "O Departamento selecionado deve pertencer à mesma Organização."}
        )
    team = Team.objects.create(
        organization=organization,
        department=department,
        name=name,
        is_active=is_active,
    )
    record_audit_event(
        actor=actor,
        action="team_created",
        target=team,
        organization=organization,
        before={},
        after={
            "id": str(team.id),
            "organization_id": str(organization.id),
            "department_id": str(department.id) if department else None,
            "name": team.name,
            "is_active": team.is_active,
        },
    )
    return team


@transaction.atomic
def update_team(team: Team, *, department=None, name, is_active, actor=None) -> Team:
    if department and department.organization != team.organization:
        raise ValidationError(
            {"department": "O Departamento selecionado deve pertencer à mesma Organização."}
        )
    before = {
        "id": str(team.id),
        "organization_id": str(team.organization.id),
        "department_id": str(team.department.id) if team.department else None,
        "name": team.name,
        "is_active": team.is_active,
    }
    team.department = department
    team.name = name
    team.is_active = is_active
    team.save()
    after = {
        "id": str(team.id),
        "organization_id": str(team.organization.id),
        "department_id": str(team.department.id) if team.department else None,
        "name": team.name,
        "is_active": team.is_active,
    }
    record_audit_event(
        actor=actor,
        action="team_updated",
        target=team,
        organization=team.organization,
        before=before,
        after=after,
    )
    return team
