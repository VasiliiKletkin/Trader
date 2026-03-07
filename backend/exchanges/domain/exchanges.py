from .schemas import Exchange


class BinanceExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "BinanceExchangeClient"


class BitfinexExchange(Exchange):
    max_candles_per_request: int = 10000
    client_class_name: str = "BitfinexExchangeClient"


class BitgetExchange(Exchange):
    max_candles_per_request: int = 200
    client_class_name: str = "BitgetExchangeClient"


class BitMEXExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "BitMEXExchangeClient"


class BybitExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "ByBitExchangeClient"


class CoinbaseExchange(Exchange):
    max_candles_per_request: int = 300
    client_class_name: str = "CoinbaseExchangeClient"


class CoinExExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "CoinExExchangeClient"


class DeribitExchange(Exchange):
    max_candles_per_request: int = 5000
    client_class_name: str = "DeribitExchangeClient"


class GateIOExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "GateIOExchangeClient"


class HTXExchange(Exchange):
    max_candles_per_request: int = 2000
    client_class_name: str = "HTXExchangeClient"


class HyperliquidExchange(Exchange):
    max_candles_per_request: int = 5000
    client_class_name: str = "HyperliquidExchangeClient"


class KrakenExchange(Exchange):
    max_candles_per_request: int = 720
    client_class_name: str = "KrakenExchangeClient"


class KuCoinExchange(Exchange):
    max_candles_per_request: int = 200
    client_class_name: str = "KuCoinExchangeClient"


class MEXCExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "MEXCExchangeClient"


class OKXExchange(Exchange):
    max_candles_per_request: int = 300
    client_class_name: str = "OKXExchangeClient"


class ParadexExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "ParadexExchangeClient"


class PhemexExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "PhemexExchangeClient"


class WooFiProExchange(Exchange):
    max_candles_per_request: int = 1000
    client_class_name: str = "WooFiProExchangeClient"
