"""WS-стримы."""

from __future__ import annotations

import asyncio
import traceback
from abc import ABC, abstractmethod

from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain.cache import ExchangeCache
from exchange_clients.domain.schemas import ExchangeClientBalance, ExchangeClientOrder
from exchanges.domain import Timeframe, TradingPair


class BaseStream(ABC):
    """Базовый WebSocket-стрим с exponential backoff."""

    MAX_BACKOFF = 60
    exchange_client_id: int

    @property
    @abstractmethod
    def key(self) -> tuple:
        raise NotImplementedError

    async def run(
        self,
        exchange_client: AbstractExchangeClient,
        shutdown_event: asyncio.Event,
    ) -> None:
        """Основной цикл: process + backoff при ошибках."""
        backoff = 1
        while not shutdown_event.is_set():
            try:
                await self._process(exchange_client)
                backoff = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                tb = traceback.format_exc()
                self._on_error(e, tb)
                await asyncio.sleep(min(backoff, self.MAX_BACKOFF))
                backoff = min(backoff * 2, self.MAX_BACKOFF)

    @abstractmethod
    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        raise NotImplementedError

    def _on_error(self, error: Exception, tb: str) -> None:
        """Логирование ошибки."""
        logger.error(f"{type(self).__name__}: {error}\n{tb}")


class BalanceStream(BaseStream):
    """Стрим баланса: watch_balance → Redis cache."""

    def __init__(
        self,
        exchange_client_id: int,
        cache: ExchangeCache,
    ) -> None:
        self.exchange_client_id = exchange_client_id
        self.cache = cache

    @property
    def key(self) -> tuple:
        return (self.exchange_client_id, type(self).__name__)

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        balances: list[ExchangeClientBalance] = await exchange_client.watch_balance()
        await self.cache.set_balances(
            exchange_client_id=self.exchange_client_id,
            balances=balances,
        )


class OrdersStream(BaseStream):
    """Стрим ордеров: watch_orders → Redis cache."""

    def __init__(
        self,
        exchange_client_id: int,
        cache: ExchangeCache,
        trading_pair: TradingPair,
    ) -> None:
        self.exchange_client_id = exchange_client_id
        self.cache = cache
        self.trading_pair = trading_pair

    @property
    def key(self) -> tuple:
        return (
            self.exchange_client_id,
            type(self).__name__,
            self.trading_pair.symbol,
        )

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        orders: list[ExchangeClientOrder] = await exchange_client.watch_orders(
            self.trading_pair
        )
        await self.cache.add_orders(
            exchange_client_id=self.exchange_client_id,
            orders=orders,
        )


class CandleStream(BaseStream):
    """Стрим свечей: watch_ohlcv → Redis cache."""

    def __init__(
        self,
        exchange_client_id: int,
        cache: CandleRedisCache,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> None:
        self.exchange_client_id = exchange_client_id
        self.cache = cache
        self.trading_pair = trading_pair
        self.timeframe = timeframe

    @property
    def key(self) -> tuple:
        return (
            self.exchange_client_id,
            type(self).__name__,
            self.trading_pair.symbol,
            self.timeframe.value,
        )

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        candles = await exchange_client.watch_ohlcv(
            self.trading_pair,
            self.timeframe,
        )
        for candle in candles:
            await self.cache.set_candle(
                exchange=exchange_client.exchange,
                trading_pair=self.trading_pair,
                timeframe=self.timeframe,
                candle=candle,
            )


class OrderBookStream(BaseStream):
    """Стрим стакана: watch_order_book."""

    def __init__(
        self,
        exchange_client_id: int,
        trading_pair: TradingPair,
        limit: int = 20,
    ) -> None:
        self.exchange_client_id = exchange_client_id
        self.trading_pair = trading_pair
        self.limit = limit

    @property
    def key(self) -> tuple:
        return (
            self.exchange_client_id,
            type(self).__name__,
            self.trading_pair.symbol,
        )

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        await exchange_client.watch_order_book(
            self.trading_pair,
            self.limit,
        )
