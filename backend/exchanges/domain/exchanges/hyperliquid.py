from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class HyperliquidExchange(Exchange):
    """HyperliquidExchange."""

    client_class_name: str = "HyperliquidExchangeClient"
