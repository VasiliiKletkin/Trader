from django.apps import AppConfig


class StrategiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "strategies"

    def ready(self):
        from strategies.domain.strategies.renko import RenkoStrategy
        from strategies.charts import renko
