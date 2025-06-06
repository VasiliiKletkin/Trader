from abc import ABC, abstractmethod
import inspect
from typing import Literal

from exchanges.domain.exchanges.schemas import Candle
from core.utils import Registry

SignalType = Literal["buy", "sell", "hold"]


class StrategyRegistry(Registry):
    pass


class AbstractStrategy(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            StrategyRegistry.register(cls)

    @abstractmethod
    async def handle_candle(self, candle: Candle):
        """Обработка новых свечей
        Args:
            candle (Candle): _description_
        """
        pass

    @abstractmethod
    async def get_signal(self) -> SignalType:
        pass
