"""
Базовый интерфейс для провайдеров свечей.

CandleProvider - абстракция для получения свечей из различных источников:
- PlainCandleProvider - прямые свечи с биржи, обернутые в ProviderCandle
- DivisionCandleProvider - синтетические свечи через деление (арбитраж)
- MinusCandleProvider - синтетические свечи через вычитание (спред)
"""

import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator, List

from core.utils.registry import Registry
from exchanges.domain import ExchangeCandle
from .shemas import ProviderCandle


class CandleProviderRegistry(Registry):
    """Реестр всех провайдеров свечей"""

    pass


class AbstractCandleProvider(ABC):
    """
    Базовый интерфейс для предоставления свечей.

    Все наследники автоматически регистрируются в CandleProviderRegistry
    через механизм __init_subclass__.
    """

    def __init_subclass__(cls, **kwargs):
        """Автоматическая регистрация подклассов в CandleProviderRegistry"""
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            CandleProviderRegistry.register(cls)

    @abstractmethod
    def get_candle(self, *candles: ExchangeCandle) -> ProviderCandle:
        """
        Получить свечу на основе доменных свечей

        Args:
            candles: Доменные свечи

        Returns:
            ProviderCandle: Всегда возвращает ProviderCandle с source_candles

        Raises:
            DoesNotExist: Если свеча не найдена
        """
        pass

    @abstractmethod
    def get_candles(self, start: datetime, end: datetime) -> List[ProviderCandle]:
        """
        Получить список свечей за период

        Args:
            start: Начало периода
            end: Конец периода

        Returns:
            List[ProviderCandle]: Список свечей, отсортированных по timestamp
        """
        pass

    @abstractmethod
    def get_last_candles(self, count: int) -> List[ProviderCandle]:
        """
        Получить последние N свечей

        Args:
            count: Количество свечей

        Returns:
            List[ProviderCandle]: Последние свечи, отсортированные по timestamp (старые -> новые)
        """
        pass

    @abstractmethod
    def get_candle_iterator(
        self, start: datetime, end: datetime
    ) -> Iterator[ProviderCandle]:
        """
        Генератор свечей за период (для бэктеста)

        Оптимизирован для работы с большими объемами данных.
        Использует итерацию по БД вместо загрузки всех данных в память.

        Args:
            start: Начало периода
            end: Конец периода

        Yields:
            ProviderCandle: Свечи по одной, отсортированные по timestamp
        """
        pass
