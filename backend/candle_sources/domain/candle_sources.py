from typing import List, Iterator, Optional
from .base import AbstractCandleSource
from exchanges.domain import ExchangeCandle, SyntheticCandle


class PlainCandleSource(AbstractCandleSource):
    def __init__(self, candle_iterator: Iterator[ExchangeCandle]):
        self.candle_iterator = candle_iterator

    def get_candle(self, candle: ExchangeCandle) -> SyntheticCandle:
        """Создает синтетическую свечу из одной исходной свечи."""
        return SyntheticCandle(
            dt_unix=candle.dt_unix,
            high=candle.high,
            low=candle.low,
            open=candle.open,
            close=candle.close,
            volume=candle.volume,
            source_candles=[candle],
        )

    def get_candles(self) -> List[SyntheticCandle]:
        return [self.get_candle(candle) for candle in self.candle_iterator]

    def get_candle_iterator(self) -> Iterator[SyntheticCandle]:
        return (self.get_candle(candle) for candle in self.candle_iterator)

    def get_last_candles(self, count: Optional[int] = 1000) -> List[SyntheticCandle]:
        last_candles = list(self.candle_iterator)[-count:]
        return [self.get_candle(candle) for candle in last_candles]


class DivisionCandleSource(AbstractCandleSource):
    def __init__(
        self,
        candle_iterator1: Iterator[ExchangeCandle],
        candle_iterator2: Iterator[ExchangeCandle],
    ):
        self.candle_iterator1 = candle_iterator1
        self.candle_iterator2 = candle_iterator2

    def get_candle(
        self,
        candle1: ExchangeCandle,
        candle2: ExchangeCandle,
    ) -> SyntheticCandle:
        """Создает синтетическую свечу делением двух исходных свечей (для арбитража)."""
        if (
            candle2.open == 0
            or candle2.high == 0
            or candle2.low == 0
            or candle2.close == 0
        ):
            raise ValueError("Деление на ноль в свечах")
        return SyntheticCandle(
            dt_unix=candle1.dt_unix,
            open=candle1.open / candle2.open,
            high=candle1.high / candle2.high,
            low=candle1.low / candle2.low,
            close=candle1.close / candle2.close,
            volume=(
                candle1.volume / candle2.volume if candle2.volume != 0 else 0
            ),
            source_candles=[candle1, candle2],
        )

    def get_candles(self) -> List[SyntheticCandle]:
        candles1 = list(self.candle_iterator1)
        candles2 = list(self.candle_iterator2)
        return [self.get_candle(c1, c2) for c1, c2 in zip(candles1, candles2)]

    def get_candle_iterator(self) -> Iterator[SyntheticCandle]:
        return (
            self.get_candle(c1, c2)
            for c1, c2 in zip(self.candle_iterator1, self.candle_iterator2)
        )

    def get_last_candles(self, count: int = 1000) -> List[SyntheticCandle]:
        last_candles1 = list(self.candle_iterator1)[-count:]
        last_candles2 = list(self.candle_iterator2)[-count:]
        return [self.get_candle(c1, c2) for c1, c2 in zip(last_candles1, last_candles2)]
