from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class BitfinexExchange(Exchange):
    """BitfinexExchange."""

    client_class_name: str = "BitfinexExchangeClient"
