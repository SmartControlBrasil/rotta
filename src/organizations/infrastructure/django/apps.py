from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "src.organizations.infrastructure.django"
    label = "organizations"

    def ready(self) -> None:
        from . import signals  # noqa: F401
