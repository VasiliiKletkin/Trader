from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class WooFiProExchange(Exchange):
    """WooFiProExchange."""

    client_class_name: str = "WooFiProExchangeClient"
