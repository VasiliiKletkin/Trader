from django.apps import AppConfig


class TradersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "traders"
    verbose_name = "Трейдеры"

    def ready(self):
        from . import charts  # noqa: F401
