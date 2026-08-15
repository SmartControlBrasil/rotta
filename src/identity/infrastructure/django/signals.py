import threading

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from src.audit.infrastructure.django.services import record_audit_event

from .models import MembershipRole, User

_skip_audit_local = threading.local()


@receiver(post_save, sender=User)
def audit_user_changes(sender, instance: User, created: bool, **kwargs) -> None:
    if getattr(_skip_audit_local, "value", False) or getattr(instance, "_skip_audit", False):
        return
    record_audit_event(
        action="user_created" if created else "user_updated",
        actor=getattr(instance, "_audit_actor", None),
        target=instance,
        after={
            "username": "[REDACTED]",
            "email": "[REDACTED]",
            "is_active": instance.is_active,
        },
    )


@receiver(post_save, sender=MembershipRole)
def audit_role_assignment(sender, instance: MembershipRole, created: bool, **kwargs) -> None:
    if created:
        record_audit_event(
            action="role_assigned",
            actor=None,
            organization=instance.membership.organization,
            target=instance.membership,
            after={"role": instance.role.code, "scope": instance.scope},
        )


@receiver(post_delete, sender=MembershipRole)
def audit_role_removal(sender, instance: MembershipRole, **kwargs) -> None:
    record_audit_event(
        action="role_removed",
        actor=None,
        organization=instance.membership.organization,
        target=instance.membership,
        before={"role": instance.role.code, "scope": instance.scope},
    )
