from django.apps import AppConfig


class ExchangesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exchanges"

    def ready(self):
        from .domain.exchanges.bybit import ByBitExchange
        from .charts import CandleSource
