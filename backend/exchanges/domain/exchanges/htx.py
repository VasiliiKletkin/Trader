from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class HTXExchange(Exchange):
    """HTXExchange."""

    client_class_name: str = "HTXExchangeClient"
