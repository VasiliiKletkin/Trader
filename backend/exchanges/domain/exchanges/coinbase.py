from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class CoinbaseExchange(Exchange):
    """CoinbaseExchange."""

    client_class_name: str = "CoinbaseExchangeClient"
