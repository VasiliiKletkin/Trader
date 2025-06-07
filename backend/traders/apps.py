from django.apps import AppConfig


class TradersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "traders"

    def ready(self):
        from . import charts
        from . import tasks
