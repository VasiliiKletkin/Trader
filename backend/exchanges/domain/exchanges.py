from .schemas import Exchange


class BinanceExchange(Exchange):
    client_class_name: str = "BinanceExchangeClient"


class BitfinexExchange(Exchange):
    client_class_name: str = "BitfinexExchangeClient"


class BitgetExchange(Exchange):
    client_class_name: str = "BitgetExchangeClient"


class BitMEXExchange(Exchange):
    client_class_name: str = "BitMEXExchangeClient"


class BybitExchange(Exchange):
    client_class_name: str = "ByBitExchangeClient"


class CoinbaseExchange(Exchange):
    client_class_name: str = "CoinbaseExchangeClient"


class CoinExExchange(Exchange):
    client_class_name: str = "CoinExExchangeClient"


class DeribitExchange(Exchange):
    client_class_name: str = "DeribitExchangeClient"


class GateIOExchange(Exchange):
    client_class_name: str = "GateIOExchangeClient"


class HTXExchange(Exchange):
    client_class_name: str = "HTXExchangeClient"


class HyperliquidExchange(Exchange):
    client_class_name: str = "HyperliquidExchangeClient"


class KrakenExchange(Exchange):
    client_class_name: str = "KrakenExchangeClient"


class KuCoinExchange(Exchange):
    client_class_name: str = "KuCoinExchangeClient"


class MEXCExchange(Exchange):
    client_class_name: str = "MEXCExchangeClient"


class OKXExchange(Exchange):
    client_class_name: str = "OKXExchangeClient"


class ParadexExchange(Exchange):
    client_class_name: str = "ParadexExchangeClient"


class PhemexExchange(Exchange):
    client_class_name: str = "PhemexExchangeClient"


class WooFiProExchange(Exchange):
    client_class_name: str = "WooFiProExchangeClient"
