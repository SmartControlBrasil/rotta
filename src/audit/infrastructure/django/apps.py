from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "src.audit.infrastructure.django"
    label = "audit"

    def ready(self) -> None:
        from . import middleware  # noqa: F401
