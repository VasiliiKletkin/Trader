from django.apps import AppConfig


class ExchangeClientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exchange_clients"
    verbose_name = "Клиенты бирж"

    def ready(self):
        import exchange_clients.domain.messages.handlers  # noqa: F401
