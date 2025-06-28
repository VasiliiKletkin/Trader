from django.apps import AppConfig


class RiskManagersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "risk_managers"

    def ready(self):
        from .domain import risk_managers
