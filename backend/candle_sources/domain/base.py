from abc import ABC, abstractmethod

from core.utils.registry import Registry
from exchanges.domain import Candle


class CandleSourceRegistry(Registry):
    pass


class AbstractCandleSource(ABC):
    @abstractmethod
    def get_candles(self) -> list[Candle]:
        pass

    @abstractmethod
    def get_candle(self, *args) -> Candle:
        pass

    @abstractmethod
    def get_last_candles(self, count: int) -> list[Candle]:
        pass
