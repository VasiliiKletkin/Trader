from typing import Optional

from exchanges.domain import Candle, ExchangeCandle


class ProviderCandle(Candle):
    first_candle: ExchangeCandle
    second_candle: Optional[ExchangeCandle] = None
