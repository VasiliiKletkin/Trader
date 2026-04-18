from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class BitgetExchange(Exchange):
    """BitgetExchange."""

    client_class_name: str = "BitgetExchangeClient"
