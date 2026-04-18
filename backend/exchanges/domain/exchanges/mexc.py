from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class MEXCExchange(Exchange):
    """MEXCExchange."""

    client_class_name: str = "MEXCExchangeClient"
