from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class PhemexExchange(Exchange):
    """PhemexExchange."""

    client_class_name: str = "PhemexExchangeClient"
