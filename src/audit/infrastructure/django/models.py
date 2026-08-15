from django.conf import settings
from django.db import models

from src.shared.infrastructure.django.models import UUIDPrimaryKeyModel


class AuditLog(UUIDPrimaryKeyModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        blank=True,
        null=True,
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        blank=True,
        null=True,
    )
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=160, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    before = models.JSONField(blank=True, null=True)
    after = models.JSONField(blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    request_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["request_id"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValueError("AuditLog entries are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"
