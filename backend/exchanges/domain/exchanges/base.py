from abc import ABC, abstractmethod
from datetime import datetime
import inspect
from typing import Any, Dict, List

from exchanges.domain.exchanges.schemas import Candle
from core.utils import Registry


class ExchangeRegistry(Registry):
    pass


class AbstractExchange(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            ExchangeRegistry.register(cls)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @abstractmethod
    async def connect(self) -> None:
        """Установить соединение с биржей (если нужно)."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Закрыть соединение (если используется WebSocket)."""
        pass

    @abstractmethod
    async def get_market_candles(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        limit: int,
    ) -> List[Candle]:
        """Получить свечи c биржи."""
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """Получить текущий баланс пользователя."""
        pass

    @abstractmethod
    async def get_price(self, symbol: str) -> float:
        """Получить последнюю цену для пары."""
        pass

    @abstractmethod
    async def create_market_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> Dict[str, Any]:
        """Создать рыночный ордер."""
        pass

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Получить список открытых ордеров."""
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> None:
        """Отменить все открытые ордера."""
        pass
