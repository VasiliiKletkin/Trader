from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class DeribitExchange(Exchange):
    """DeribitExchange."""

    client_class_name: str = "DeribitExchangeClient"
