import asyncio
import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any

from ccxt.base.types import OrderSide

from core.utils.registry import Registry
from exchanges.domain import Candle, Timeframe, TradingPair

from .schemas import ExchangeClientBalance, ExchangeClientOrder


class ExchangeClientRegistry(Registry):
    pass


class AbstractExchangeClient(ABC):
    exchange: Any = None
    max_concurrent_requests: int = 3

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
    ) -> list[Candle]:
        """Получить свечи c биржи."""
        pass

    @abstractmethod
    async def get_balances(self) -> list[ExchangeClientBalance]:
        """Получить текущий баланс пользователя."""
        pass

    @abstractmethod
    async def get_open_orders(
        self,
        trading_pair: TradingPair | None = None,
    ) -> list[dict[str, Any]]:
        """Получить список открытых ордеров."""
        pass

    @abstractmethod
    async def get_orders(
        self,
        trading_pair: TradingPair | None = None,
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[ExchangeClientOrder]:
        """Получить все ордера пользователя (история ордеров)."""
        pass

    @abstractmethod
    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Decimal | None = None,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        """Создать рыночный ордер."""
        pass

    @abstractmethod
    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        """Отменить все открытые ордера."""
        pass

    @abstractmethod
    def _create_exchange(self) -> None:
        """Создаёт ccxt exchange instance. Вызывается в __init__."""
        pass

    def _apply_throttle(self) -> None:
        """Оборачивает exchange.fetch семафором для ограничения параллельных запросов."""
        semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        original_fetch = self.exchange.fetch

        async def throttled_fetch(*args, **kwargs):
            async with semaphore:
                return await original_fetch(*args, **kwargs)

        self.exchange.fetch = throttled_fetch

    async def __aenter__(self) -> "AbstractExchangeClient":
        await self.exchange.__aenter__()
        self._apply_throttle()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.exchange is not None:
            await self.exchange.__aexit__(exc_type, exc, tb)
