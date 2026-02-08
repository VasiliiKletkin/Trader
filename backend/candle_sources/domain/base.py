import inspect
from abc import ABC, abstractmethod

from core.utils.registry import Registry
from exchanges.domain import Candle


class CandleSourceRegistry(Registry):
    pass


class AbstractCandleSource(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            CandleSourceRegistry.register(cls)

    # @abstractmethod
    # def get_candle_iterator(
    #     self,
    #     date_start: Optional[datetime],
    #     date_from: Optional[datetime],
    # ) -> Iterator[Candle]:
    #     pass
    @abstractmethod
    def get_candles(self) -> list[Candle]:
        pass

    @abstractmethod
    def get_candle(self, *args) -> Candle:
        pass

    @abstractmethod
    def get_last_candles(self, count: int) -> list[Candle]:
        pass
