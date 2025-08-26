from decimal import Decimal
import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from ccxt.base.types import OrderSide
from core.utils.registry import Registry

from exchange_clients.domain.schemas import ExchangeClientOrder, TradingPair
from exchanges.domain.schemas import Candle


class ExchangeClientRegistry(Registry):
    pass


class AbstractExchangeClient(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            ExchangeClientRegistry.register(cls)

    @abstractmethod
    def get_candles(
        self,
        trading_pair: str,
        timeframe: str,
        since: datetime,
        limit: int,
    ) -> List[Candle]:
        """Получить свечи c биржи."""
        pass

    @abstractmethod
    def get_balances(self) -> Dict[str, Decimal]:
        """Получить текущий баланс пользователя."""
        pass

    @abstractmethod
    def get_open_orders(self, trading_pair: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить список открытых ордеров."""
        pass

    @abstractmethod
    def get_orders(
        self,
        trading_pair: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[ExchangeClientOrder]:
        """Получить все ордера пользователя (история ордеров)."""
        pass

    @abstractmethod
    def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Optional[Decimal] = None,
        params: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Создать рыночный ордер."""
        pass

    @abstractmethod
    def cancel_all_orders(self, trading_pair: str) -> None:
        """Отменить все открытые ордера."""
        pass
