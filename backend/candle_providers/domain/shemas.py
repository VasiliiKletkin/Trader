from typing import Optional

from exchanges.domain import Candle, ExchangeCandle


class ProviderCandle(Candle):
    primary_candle: ExchangeCandle
    secondary_candle: Optional[ExchangeCandle] = None
