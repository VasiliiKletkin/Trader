from collections.abc import Iterator
import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.utils.registry import Registry

from exchanges.domain import ExchangeCandle, SyntheticCandle


class CandleSourceRegistry(Registry):
    pass


class AbstractCandleSource(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            CandleSourceRegistry.register(cls)

    @abstractmethod
    def get_candle(self, *candles: ExchangeCandle) -> SyntheticCandle:
        """Создает синтетическую свечу из одной или нескольких исходных свечей."""
        pass

    @abstractmethod
    def get_candles(
        self,
    ) -> List[SyntheticCandle]:
        pass

    @abstractmethod
    def get_candle_iterator(
        self,
    ) -> Iterator[SyntheticCandle]:
        pass

    @abstractmethod
    def get_last_candles(self, count: int) -> List[SyntheticCandle]:
        pass
