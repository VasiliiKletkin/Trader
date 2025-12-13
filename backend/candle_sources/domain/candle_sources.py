from typing import List, Iterator
from .base import AbstractCandleSource
from exchanges.domain import Candle


class PlainCandleSource(AbstractCandleSource):
    def __init__(self, candles: List[Candle], *args):
        self.candles = candles

    def get_candle(self, candle: Candle, *args) -> Candle:
        return candle

    def get_candles(self) -> List[Candle]:
        return list(self.get_candle(candle) for candle in self.candles)

    def get_last_candles(self, count: int) -> List[Candle]:
        return self.candles[-count:] if count <= len(self.candles) else self.candles


class DivisionCandleSource(AbstractCandleSource):
    def __init__(self, candles1: List[Candle], candles2: List[Candle], *args):
        self.candles1 = candles1
        self.candles2 = candles2

    def get_candle(
        self,
        candle1: Candle,
        candle2: Candle,
        *args,
    ) -> Candle:
        if (
            candle2.open == 0
            or candle2.high == 0
            or candle2.low == 0
            or candle2.close == 0
        ):
            raise ValueError("Деление на ноль в свечах")
        return Candle(
            ids=[candle1.ids, candle2.ids],
            dt_unix=candle1.dt_unix,
            timestamp=candle1.timestamp,
            open=candle1.open / candle2.open,
            high=candle1.high / candle2.high,
            low=candle1.low / candle2.low,
            close=candle1.close / candle2.close,
            volume=candle1.volume / candle2.volume if candle2.volume != 0 else 0,
        )

    def get_candles(self) -> List[Candle]:
        return [self.get_candle(c1, c2) for c1, c2 in zip(self.candles1, self.candles2)]

    def get_last_candles(self, count: int) -> List[Candle]:
        candles1 = (
            self.candles1[-count:] if count <= len(self.candles1) else self.candles1
        )
        candles2 = (
            self.candles2[-count:] if count <= len(self.candles2) else self.candles2
        )
        return [self.get_candle(c1, c2) for c1, c2 in zip(candles1, candles2)]
