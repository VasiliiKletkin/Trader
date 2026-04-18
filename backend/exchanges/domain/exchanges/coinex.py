from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class CoinExExchange(Exchange):
    """CoinExExchange."""

    client_class_name: str = "CoinExExchangeClient"
