from django.db.models.signals import post_save
from django.dispatch import receiver

from src.audit.infrastructure.django.services import record_audit_event

from .models import MembershipRole, User


@receiver(post_save, sender=User)
def audit_user_changes(sender, instance: User, created: bool, **kwargs) -> None:
    record_audit_event(
        action="user_created" if created else "user_updated",
        actor=None,
        target=instance,
        after={
            "username": instance.username,
            "email": instance.email,
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
