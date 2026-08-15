from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "src.identity.infrastructure.django"
    label = "identity"

    def ready(self) -> None:
        from . import signals  # noqa: F401
