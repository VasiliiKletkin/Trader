from django.apps import AppConfig


class ExchangesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exchanges"
    verbose_name = "Биржи"

    def ready(self):
        from . import charts  # noqa: F401
