from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class KrakenExchange(Exchange):
    """KrakenExchange."""

    client_class_name: str = "KrakenExchangeClient"
