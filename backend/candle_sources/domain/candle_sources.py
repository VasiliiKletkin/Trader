from typing import List, Iterator
from .base import AbstractCandleSource
from exchanges.domain import Candle


class PlainCandleSource(AbstractCandleSource):
    def __init__(self, candle_iterators: List[Iterator[Candle]]):
        self.candle_iterators = candle_iterators

    def get_candles(self) -> List[Candle]:
        return list(self.candle_iterators[0])

    def get_candle_iterator(self) -> Iterator[Candle]:
        return self.candle_iterators[0]

    def get_last_candles(self, count: int = 1000) -> List[Candle]:
        candles = list(self.candle_iterators[0])
        return candles[-count:]


class DivisionCandleSource(AbstractCandleSource):
    def __init__(self, candle_iterators: List[Iterator[Candle]]):
        if len(candle_iterators) != 2:
            raise ValueError("DivisionCandleSource требует ровно 2 итератора")
        self.candle_iterators = candle_iterators

    def _divide_candles(self, c1: Candle, c2: Candle) -> Candle:
        """
        Делит значения первой свечи на вторую.
        """
        if c2.open == 0 or c2.high == 0 or c2.low == 0 or c2.close == 0:
            raise ValueError("Деление на ноль в свечах")
        return Candle(
            timestamp=c1.timestamp,
            open=c1.open / c2.open,
            high=c1.high / c2.high,
            low=c1.low / c2.low,
            close=c1.close / c2.close,
            volume=c1.volume / c2.volume if c2.volume != 0 else 0,
        )

    def get_candles(self) -> List[Candle]:
        candles = []
        for c1, c2 in zip(self.candle_iterators[0], self.candle_iterators[1]):
            divided = self._divide_candles(c1, c2)
            candles.append(divided)
        return candles

    def get_candle_iterator(self) -> Iterator[Candle]:
        for c1, c2 in zip(self.candle_iterators[0], self.candle_iterators[1]):
            yield self._divide_candles(c1, c2)

    def get_last_candles(self, count: int) -> List[Candle]:
        candles = []
        iter1 = list(self.candle_iterators[0])[-count:]
        iter2 = list(self.candle_iterators[1])[-count:]
        for c1, c2 in zip(iter1, iter2):
            divided = self._divide_candles(c1, c2)
            candles.append(divided)
        return candles