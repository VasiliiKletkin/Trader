"""
Реализации провайдеров свечей.

PlainCandleProvider - оборачивает ExchangeCandle в ProviderCandle с одной source_candle
DivisionCandleProvider - создает ProviderCandle делением двух источников (арбитраж)
MinusCandleProvider - создает ProviderCandle вычитанием двух источников (спред)
"""

from datetime import datetime
from typing import Iterator, List, TYPE_CHECKING

from exchanges.domain import ExchangeCandle
from .base import AbstractCandleProvider
from .shemas import ProviderCandle

if TYPE_CHECKING:
    from candle_providers.models import CandleSource as CandleSourceORM


class PlainCandleProvider(AbstractCandleProvider):
    """
    Прямой источник свечей с биржи.

    Оборачивает ExchangeCandle в ProviderCandle с одной source_candle.
    Используется для обычных трейдеров (не арбитражных).
    """

    def __init__(self, source: "CandleSourceORM"):
        """
        Args:
            source: Источник свечей от биржи
        """
        self.source = source
        self.source_id = source.id

    def get_candle(self, candle: ExchangeCandle) -> ProviderCandle:
        """Возвращает ProviderCandle с одной source_candle"""
        return ProviderCandle(
            dt_unix=candle.dt_unix,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            primary_candle=candle,
            secondary_candle=None,
        )

    def get_candles(self, start: datetime, end: datetime) -> List[ProviderCandle]:
        """Получает список свечей за период"""
        candles_orm = self.source.get_candles(start=start, end=end)
        return [self.get_candle(c.instantiate()) for c in candles_orm]

    def get_last_candles(self, count: int) -> List[ProviderCandle]:
        """Получает последние N свечей"""
        return [
            self.get_candle(candle.instantiate())
            for candle in self.source.get_last_candles(count)
        ]

    def get_candle_iterator(
        self, start: datetime, end: datetime
    ) -> Iterator[ProviderCandle]:
        for candle_orm in self.source.get_candle_iterator(start=start, end=end):
            yield self.get_candle(candle_orm.instantiate())


class DivisionCandleProvider(AbstractCandleProvider):
    """
    Синтетический источник для арбитража - деление цен двух бирж.

    Создает ProviderCandle путем деления OHLC значений:
    result = source_1 / source_2
    """

    def __init__(
        self,
        source_1: "CandleSourceORM",
        source_2: "CandleSourceORM",
    ):
        if source_1.timeframe != source_2.timeframe:
            raise ValueError("Sources must have same timeframe")
        if source_1.trading_pair != source_2.trading_pair:
            raise ValueError("Sources must have same trading pair")

        self.source_1 = PlainCandleProvider(source_1)
        self.source_2 = PlainCandleProvider(source_2)

    def get_candle(
        self, candle_1: ExchangeCandle, candle_2: ExchangeCandle
    ) -> ProviderCandle:
        return ProviderCandle(
            dt_unix=candle_1.dt_unix,
            open=candle_1.open / candle_2.open,
            high=candle_1.high / candle_2.high,
            low=candle_1.low / candle_2.low,
            close=candle_1.close / candle_2.close,
            volume=min(candle_1.volume, candle_2.volume),
            primary_candle=candle_1,
            secondary_candle=candle_2,
        )

    def get_candles(self, start: datetime, end: datetime) -> List[ProviderCandle]:
        """Получает список синтетических свечей за период"""
        candles_1 = self.source_1.get_candles(start, end)
        candles_2 = self.source_2.get_candles(start, end)
        return [
            self.get_candle(c1.primary_candle, c2.primary_candle)
            for c1, c2 in zip(candles_1, candles_2)
        ]

    def get_last_candles(self, count: int) -> List[ProviderCandle]:
        """Получает последние N синтетических свечей"""
        candles_1 = self.source_1.get_last_candles(count)
        candles_2 = self.source_2.get_last_candles(count)

        return [
            self.get_candle(c1.primary_candle, c2.primary_candle)
            for c1, c2 in zip(candles_1, candles_2)
        ]

    def get_candle_iterator(
        self, start: datetime, end: datetime
    ) -> Iterator[ProviderCandle]:
        """
        Генератор синтетических свечей.

        Итерируется по двум источникам параллельно.
        """
        iter_1 = self.source_1.get_candle_iterator(start, end)
        iter_2 = self.source_2.get_candle_iterator(start, end)
        for c1, c2 in zip(iter_1, iter_2):
            yield self.get_candle(c1.primary_candle, c2.primary_candle)


class MinusCandleProvider(AbstractCandleProvider):
    """
    Синтетический источник для торговли спредом - вычитание цен двух бирж.

    Создает ProviderCandle путем вычитания OHLC значений:
    result = source_1 - source_2
    """

    def __init__(
        self,
        source_1: "CandleSourceORM",
        source_2: "CandleSourceORM",
    ):
        """
        Args:
            source_1: Первый источник (уменьшаемое)
            source_2: Второй источник (вычитаемое)
        """

        if source_1.timeframe != source_2.timeframe:
            raise ValueError("Sources must have same timeframe")
        if source_1.trading_pair != source_2.trading_pair:
            raise ValueError("Sources must have same trading pair")

        self.source_1 = PlainCandleProvider(source_1)
        self.source_2 = PlainCandleProvider(source_2)

    def get_candle(
        self, candle_1: ExchangeCandle, candle_2: ExchangeCandle
    ) -> ProviderCandle:
        return ProviderCandle(
            dt_unix=candle_1.dt_unix,
            open=candle_1.open - candle_2.open,
            high=candle_1.high - candle_2.high,
            low=candle_1.low - candle_2.low,
            close=candle_1.close - candle_2.close,
            volume=min(candle_1.volume, candle_2.volume),
            primary_candle=candle_1,
            secondary_candle=candle_2,
        )

    def get_candles(self, start: datetime, end: datetime) -> List[ProviderCandle]:
        """Получает список синтетических свечей за период"""
        candles_1 = self.source_1.get_candles(start, end)
        candles_2 = self.source_2.get_candles(start, end)
        return [
            self.get_candle(c1.primary_candle, c2.primary_candle)
            for c1, c2 in zip(candles_1, candles_2)
        ]

    def get_last_candles(self, count: int) -> List[ProviderCandle]:
        """Получает последние N синтетических свечей"""
        candles_1 = self.source_1.get_last_candles(count)
        candles_2 = self.source_2.get_last_candles(count)

        return [
            self.get_candle(c1.primary_candle, c2.primary_candle)
            for c1, c2 in zip(candles_1, candles_2)
        ]

    def get_candle_iterator(
        self, start: datetime, end: datetime
    ) -> Iterator[ProviderCandle]:
        """
        Генератор синтетических свечей.

        Итерируется по двум источникам параллельно.
        """
        iter_1 = self.source_1.get_candle_iterator(start, end)
        iter_2 = self.source_2.get_candle_iterator(start, end)
        for c1, c2 in zip(iter_1, iter_2):
            yield self.get_candle(c1.primary_candle, c2.primary_candle)
