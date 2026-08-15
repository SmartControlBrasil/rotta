from collections.abc import Mapping
from typing import Any

from django.db import transaction

SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "authorization", "credential"}


def sanitize_audit_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized = {}
        for key, nested_value in value.items():
            if any(secret in str(key).lower() for secret in SENSITIVE_KEYS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_audit_payload(nested_value)
        return sanitized
    if isinstance(value, list):
        return [sanitize_audit_payload(item) for item in value]
    return value


def record_audit_event(
    *,
    action: str,
    actor=None,
    organization=None,
    target=None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str = "",
    request_id: str = "",
):
    from .models import AuditLog

    target_type = ""
    target_id = ""
    if target is not None:
        target_type = f"{target.__class__.__module__}.{target.__class__.__name__}"
        target_id = str(getattr(target, "pk", ""))

    def create_log():
        return AuditLog.objects.create(
            actor=actor if getattr(actor, "is_authenticated", True) else None,
            organization=organization,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=sanitize_audit_payload(before),
            after=sanitize_audit_payload(after),
            metadata=sanitize_audit_payload(metadata),
            ip_address=ip_address,
            user_agent=user_agent[:1000],
            request_id=request_id,
        )

    return transaction.on_commit(create_log)
