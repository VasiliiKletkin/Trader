from ..schemas import Exchange, ExchangeRegistry


@ExchangeRegistry.register
class TBankExchange(Exchange):
    """T-Bank Invest (акции/облигации/ETF/фьючерсы MOEX)."""

    client_class_name: str = "TBankExchangeClient"
