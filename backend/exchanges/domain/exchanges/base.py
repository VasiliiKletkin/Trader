import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

from core.utils.registry import Registry
from exchanges.domain.schemas import Candle


class ExchangeRegistry(Registry):
    pass


class AbstractExchange(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            ExchangeRegistry.register(cls)

    @abstractmethod
    def get_market_candles(
        self,
        trading_pair: str,
        timeframe: str,
        since: datetime,
        limit: int,
    ) -> List[Candle]:
        """Получить свечи c биржи."""
        pass

    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """Получить текущий баланс пользователя."""
        pass

    @abstractmethod
    def get_price(self, trading_pair: str) -> float:
        """Получить последнюю цену для пары."""
        pass

    @abstractmethod
    def create_market_order(
        self, trading_pair: str, side: str, amount: float, price: float
    ) -> Dict[str, Any]:
        """Создать рыночный ордер."""
        pass

    @abstractmethod
    def get_open_orders(self, trading_pair: str) -> List[Dict[str, Any]]:
        """Получить список открытых ордеров."""
        pass

    @abstractmethod
    def cancel_all_orders(self, trading_pair: str) -> None:
        """Отменить все открытые ордера."""
        pass
