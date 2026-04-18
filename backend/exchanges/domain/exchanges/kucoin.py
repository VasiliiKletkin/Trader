from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class KuCoinExchange(Exchange):
    """KuCoinExchange."""

    client_class_name: str = "KuCoinExchangeClient"
