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
    client: Any = None
    exchange: Any = None

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

    async def watch_ohlcv(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
    ) -> list[Candle]:
        """Подписка на OHLCV свечи через WebSocket."""
        raise NotImplementedError

    async def __aenter__(self) -> "AbstractExchangeClient":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client is not None:
            await self.client.__aexit__(exc_type, exc, tb)
