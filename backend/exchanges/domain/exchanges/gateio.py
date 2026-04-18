from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class GateIOExchange(Exchange):
    """GateIOExchange."""

    client_class_name: str = "GateIOExchangeClient"
