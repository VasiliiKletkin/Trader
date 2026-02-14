from django.apps import AppConfig


class CandleSourcesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "candle_sources"
    verbose_name = "Источники свечей"

    def ready(self):
        from . import charts  # noqa: F401
