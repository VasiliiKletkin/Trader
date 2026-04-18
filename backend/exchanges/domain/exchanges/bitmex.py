from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class BitMEXExchange(Exchange):
    """BitMEXExchange."""

    client_class_name: str = "BitMEXExchangeClient"
