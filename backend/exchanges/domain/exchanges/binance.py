from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class BinanceExchange(Exchange):
    """BinanceExchange."""

    client_class_name: str = "BinanceExchangeClient"
