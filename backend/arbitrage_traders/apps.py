from django.apps import AppConfig


class ArbitrageTradersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "arbitrage_traders"
    verbose_name = "Арбитражные трейдеры"

    def ready(self):
        from . import charts  # noqa
