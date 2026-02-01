from decimal import Decimal
import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from ccxt.base.types import OrderSide
from core.utils.registry import Registry

from .schemas import ExchangeClientOrder
from exchanges.domain import TradingPair
from exchanges.domain import Candle
from exchanges.domain import Timeframe


class ExchangeClientRegistry(Registry):
    pass


class AbstractExchangeClient(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            ExchangeClientRegistry.register(cls)

    @abstractmethod
    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        since: datetime,
        limit: int,
    ) -> List[Candle]:
        """Получить свечи c биржи."""
        pass

    @abstractmethod
    async def get_balances(self) -> Dict[str, Decimal]:
        """Получить текущий баланс пользователя."""
        pass

    @abstractmethod
    async def get_open_orders(
        self,
        trading_pair: Optional[TradingPair] = None,
    ) -> List[Dict[str, Any]]:
        """Получить список открытых ордеров."""
        pass

    @abstractmethod
    async def get_orders(
        self,
        trading_pair: Optional[TradingPair] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[ExchangeClientOrder]:
        """Получить все ордера пользователя (история ордеров)."""
        pass

    @abstractmethod
    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: Optional[dict] = None,
    ) -> ExchangeClientOrder:
        """Создать рыночный ордер."""
        pass

    @abstractmethod
    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        """Отменить все открытые ордера."""
        pass

    def __async_enter__(self) -> "AbstractExchangeClient":
        return self

    def __async_exit__(self, exc_type, exc, tb) -> None:
        return None
