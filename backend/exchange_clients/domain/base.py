from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any

import ccxt.async_support
from ccxt.base.types import OrderSide

from core.utils.registry import Registry
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair

from .schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
)


class ExchangeClientRegistry(Registry):
    pass


class AbstractExchangeClient(ABC):
    client: ccxt.async_support.Exchange | None = None
    exchange: Exchange | None = None

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
        price: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        """Создать рыночный ордер."""
        pass

    @abstractmethod
    async def fetch_order(
        self,
        exchange_order_id: str,
        trading_pair: TradingPair,
    ) -> ExchangeClientOrder:
        """Получить ордер по ID с биржи."""
        pass

    @abstractmethod
    async def cancel_all_orders(
        self,
        trading_pair: TradingPair,
    ) -> None:
        """Отменить все открытые ордера."""
        pass

    async def watch_ohlcv(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> list[Candle]:
        """Подписка на OHLCV свечи через WebSocket (одна пара)."""
        raise NotImplementedError

    async def watch_ohlcv_for_symbols(
        self,
        subscriptions: list[tuple[TradingPair, Timeframe]],
    ) -> dict[TradingPair, dict[Timeframe, list[Candle]]]:
        """Подписка на OHLCV свечи для нескольких пар через один WebSocket.

        Args:
            subscriptions: [(TradingPair, Timeframe), ...]

        Returns:
            {TradingPair: {Timeframe: [Candle, ...]}}
        """
        raise NotImplementedError

    async def __aenter__(self) -> "AbstractExchangeClient":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client is not None:
            await self.client.__aexit__(exc_type, exc, tb)
