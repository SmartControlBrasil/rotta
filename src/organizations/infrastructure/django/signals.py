from django.db.models.signals import post_save
from django.dispatch import receiver

from src.audit.infrastructure.django.services import record_audit_event

from .models import Membership


@receiver(post_save, sender=Membership)
def audit_membership_changes(sender, instance: Membership, created: bool, **kwargs) -> None:
    record_audit_event(
        action="membership_created" if created else "membership_updated",
        actor=None,
        organization=instance.organization,
        target=instance,
        after={"user_id": str(instance.user_id), "status": instance.status},
    )
