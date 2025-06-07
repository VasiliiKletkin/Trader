from django.apps import AppConfig


class ExchangeClientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exchanges"

    def ready(self):
        from .domain.exchanges.bybit import ByBitExchangeClient
        from .charts import CandleSource
