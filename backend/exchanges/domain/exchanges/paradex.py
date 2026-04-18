from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class ParadexExchange(Exchange):
    """ParadexExchange."""

    client_class_name: str = "ParadexExchangeClient"
