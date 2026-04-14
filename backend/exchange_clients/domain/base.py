from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

import ccxt.async_support
from ccxt.base.types import OrderSide

from core.utils.registry import Registry
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from exchanges.domain.schemas import MarketType

from .schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    MarginMode,
)


class ExchangeClientRegistry(Registry):
    pass


class AbstractExchangeClient(ABC):
    client: ccxt.async_support.Exchange
    exchange: Exchange

    MARKET_TYPE_MAP: dict[str, str] = {
        MarketType.FUTURES: "swap",
        MarketType.SPOT: "spot",
    }

    def get_ccxt_market_type(self, market_type: MarketType) -> str:
        return self.MARKET_TYPE_MAP[market_type]

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
    async def fetch_balances(
        self, market_type: MarketType
    ) -> list[ExchangeClientBalance]:
        """Получить текущий баланс пользователя."""
        pass

    @abstractmethod
    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
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

    @abstractmethod
    async def set_margin_mode(
        self,
        margin_mode: MarginMode,
        trading_pair: TradingPair,
    ) -> None:
        """Установить режим маржи (isolated/cross) для торговой пары."""
        pass

    @abstractmethod
    async def set_leverage(
        self,
        leverage: float,
        trading_pair: TradingPair,
    ) -> None:
        """Установить кредитное плечо для торговой пары."""
        pass

    async def watch_balance(
        self,
        market_type: MarketType,
    ) -> list[ExchangeClientBalance]:
        """Подписка на баланс через WebSocket."""
        raise NotImplementedError

    async def watch_orders(
        self,
        trading_pair: TradingPair,
    ) -> list[ExchangeClientOrder]:
        """Подписка на ордера через WebSocket."""
        raise NotImplementedError

    async def watch_order_book(
        self,
        trading_pair: TradingPair,
        limit: int = 20,
    ) -> dict:
        """Подписка на стакан через WebSocket."""
        raise NotImplementedError

    async def watch_ohlcv(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> list[Candle]:
        """Подписка на OHLCV свечи через WebSocket (одна пара)."""
        raise NotImplementedError

    async def __aenter__(self) -> "AbstractExchangeClient":
        raise NotImplementedError

    async def __aexit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError
