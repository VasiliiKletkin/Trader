from collections.abc import Iterator
import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.utils.registry import Registry

from exchanges.domain import Candle


class CandleSourceRegistry(Registry):
    pass


class AbstractCandleSource(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            CandleSourceRegistry.register(cls)

    @abstractmethod
    def get_candles(
        self,
        date_start: Optional[datetime],
        date_from: Optional[datetime],
    ) -> List[Candle]:
        pass

    @abstractmethod
    def get_candle_iterator(
        self,
        date_start: Optional[datetime],
        date_from: Optional[datetime],
    ) -> Iterator[Candle]:
        pass

    @abstractmethod
    def get_last_candles(self, count: int) -> List[Candle]:
        pass
