import inspect
from abc import ABC, abstractmethod
from typing import Literal

from core.utils.registry import Registry
from exchanges.domain.schemas import Candle

SignalType = Literal["buy", "sell", "hold"]


class StrategyRegistry(Registry):
    pass


class AbstractStrategy(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            StrategyRegistry.register(cls)

    @abstractmethod
    def handle_candle(self, candle: Candle):
        """Обработка новых свечей
        Args:
            candle (Candle): _description_
        """
        pass

    @abstractmethod
    def get_signal(self) -> SignalType:
        pass

    @abstractmethod
    def load_data(self, data) -> None:
        pass

    @abstractmethod
    def dump_data(self):
        pass
