import inspect
from abc import ABC, abstractmethod
from enum import Enum

from core.utils.registry import Registry
from exchanges.domain.schemas import CandleDTO


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    WAIT = "wait"


class StrategyRegistry(Registry):
    pass


class AbstractStrategy(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            StrategyRegistry.register(cls)

    @abstractmethod
    def handle_candle(self, candle: CandleDTO):
        """Обработка новых свечей
        Args:
            candle (CandleDTO): _description_
        """
        pass

    @abstractmethod
    def get_signal(self) -> SignalType:
        pass

    @abstractmethod
    def load_data(self, data) -> None:
        pass

    @abstractmethod
    def dump_data(self) -> dict:
        pass
