from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "src.intelligence.infrastructure.django"
    label = "intelligence"
    verbose_name = "Intelligence"
