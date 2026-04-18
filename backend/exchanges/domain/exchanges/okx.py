from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class OKXExchange(Exchange):
    """OKXExchange."""

    client_class_name: str = "OKXExchangeClient"
