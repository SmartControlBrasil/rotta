from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db import transaction

from src.audit.infrastructure.django.services import record_audit_event
from src.identity.infrastructure.django.models import MembershipRole
from src.organizations.domain.enums import MembershipStatus
from src.organizations.infrastructure.django.models import Membership
from src.shared.domain.enums import AccessScope


@contextmanager
def skip_audit_signals():
    from src.identity.infrastructure.django.signals import _skip_audit_local

    old_val = getattr(_skip_audit_local, "value", False)
    _skip_audit_local.value = True
    try:
        yield
    finally:
        _skip_audit_local.value = old_val


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


@transaction.atomic
def create_user_with_membership(
    *,
    username,
    email,
    first_name,
    last_name,
    password,
    organization,
    role,
    scope,
    actor=None,
):
    with skip_audit_signals():
        User = get_user_model()
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
        )

        membership = Membership.objects.create(
            user=user,
            organization=organization,
            status=MembershipStatus.ACTIVE,
        )

        MembershipRole.objects.create(
            membership=membership,
            role=role,
            scope=scope,
        )

        record_audit_event(
            actor=actor,
            action="user_created",
            target=user,
            organization=organization,
            before={},
            after={
                "id": str(user.id),
                "username": "[REDACTED]",
                "email": "[REDACTED]",
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
            },
        )

        record_audit_event(
            actor=actor,
            action="user_membership_changed",
            target=user,
            organization=organization,
            before={},
            after={
                "organization_id": str(organization.id),
                "organization_name": organization.name,
                "status": MembershipStatus.ACTIVE.value,
                "role_code": role.code,
                "scope": scope,
            },
        )

        return user


@transaction.atomic
def update_user_details(user, *, email, first_name, last_name, is_active, actor=None):
    with skip_audit_signals():
        before = {
            "id": str(user.id),
            "username": "[REDACTED]",
            "email": "[REDACTED]",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
        }

        was_active = user.is_active
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = is_active
        user.save()

        after = {
            "id": str(user.id),
            "username": "[REDACTED]",
            "email": "[REDACTED]",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
        }

        primary_membership = user.memberships.filter(status="ACTIVE").first()
        org = primary_membership.organization if primary_membership else None

        record_audit_event(
            actor=actor,
            action="user_updated",
            target=user,
            organization=org,
            before=before,
            after=after,
        )

        if was_active != is_active:
            record_audit_event(
                actor=actor,
                action="user_activated" if is_active else "user_deactivated",
                target=user,
                organization=org,
                before={"is_active": was_active},
                after={"is_active": is_active},
            )

        return user


@transaction.atomic
def update_user_membership(user, *, organization, role, scope, actor=None):
    with skip_audit_signals():
        membership, created = Membership.objects.get_or_create(
            user=user,
            organization=organization,
            defaults={"status": MembershipStatus.ACTIVE},
        )
        if not created and membership.status != MembershipStatus.ACTIVE:
            membership.status = MembershipStatus.ACTIVE
            membership.save()

        old_binding = MembershipRole.objects.filter(membership=membership).first()
        before_data = {}
        if old_binding:
            before_data = {
                "organization_id": str(organization.id),
                "organization_name": organization.name,
                "role_code": old_binding.role.code,
                "scope": old_binding.scope,
            }

        MembershipRole.objects.filter(membership=membership).delete()
        MembershipRole.objects.create(
            membership=membership,
            role=role,
            scope=scope,
        )

        after_data = {
            "organization_id": str(organization.id),
            "organization_name": organization.name,
            "role_code": role.code,
            "scope": scope,
        }

        record_audit_event(
            actor=actor,
            action="user_membership_changed",
            target=user,
            organization=organization,
            before=before_data,
            after=after_data,
        )

        if not old_binding or old_binding.role != role:
            record_audit_event(
                actor=actor,
                action="user_role_changed",
                target=user,
                organization=organization,
                before={"role_code": old_binding.role.code} if old_binding else {},
                after={"role_code": role.code},
            )

        return membership
