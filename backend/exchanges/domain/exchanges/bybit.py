from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class BybitExchange(Exchange):
    """BybitExchange."""

    client_class_name: str = "ByBitExchangeClient"
