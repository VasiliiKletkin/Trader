"""WS-стримы."""

from __future__ import annotations

import asyncio
import traceback
from abc import ABC, abstractmethod

from asgiref.sync import sync_to_async
from loguru import logger

from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain.schemas import ExchangeClientBalance, ExchangeClientOrder
from exchanges.domain import Timeframe, TradingPair


class BaseStream(ABC):
    """Базовый WebSocket-стрим с exponential backoff."""

    MAX_BACKOFF = 60

    @property
    @abstractmethod
    def key(self) -> tuple:
        """Уникальный ключ стрима для reconcile."""
        ...

    @property
    @abstractmethod
    def exchange_client_id(self) -> int:
        """ID клиента для получения из пула."""
        ...

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
                await self._on_error(e, tb)
                await asyncio.sleep(min(backoff, self.MAX_BACKOFF))
                backoff = min(backoff * 2, self.MAX_BACKOFF)

    @abstractmethod
    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        """Одна итерация получения данных."""
        ...

    @abstractmethod
    async def _on_error(self, error: Exception, tb: str) -> None:
        """Обработка ошибки."""
        ...


class BalanceStream(BaseStream):
    """Стрим баланса: watch_balance → Redis cache + БД."""

    def __init__(self, exchange_client_id: int, cache) -> None:
        self._exchange_client_id = exchange_client_id
        self._cache = cache

    @property
    def key(self) -> tuple:
        return (self._exchange_client_id, type(self).__name__)

    @property
    def exchange_client_id(self) -> int:
        return self._exchange_client_id

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        balances: list[ExchangeClientBalance] = await exchange_client.watch_balance()
        await self._cache.set_balances(
            exchange_client_id=self._exchange_client_id,
            balances=balances,
        )
        await self._sync_to_db(balances)

    @sync_to_async
    def _sync_to_db(self, balances: list[ExchangeClientBalance]) -> None:
        from exchange_clients.models import (
            ExchangeClientBalance as ExchangeClientBalanceORM,
        )

        orm_balances = [
            ExchangeClientBalanceORM(
                exchange_client_id=self._exchange_client_id,
                currency=b.currency,
                free=b.free,
                used=b.used,
                total=b.total,
                debt=b.debt,
            )
            for b in balances
            if b.total > 0
        ]
        if orm_balances:
            ExchangeClientBalanceORM.objects.bulk_create(
                orm_balances,
                update_conflicts=True,
                update_fields=[
                    "free",
                    "used",
                    "debt",
                    "total",
                    "updated_at",
                ],
                unique_fields=[
                    "exchange_client",
                    "currency",
                ],
            )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str) -> None:
        from telegram_bots.tasks import send_notification

        error_type = type(error).__name__
        logger.error(
            f"BalanceStream ошибка client_id={self._exchange_client_id}"
            f" [{error_type}]: {error}\n{tb}"
        )
        send_notification.delay(
            message=(
                f"WS ошибка client_id={self._exchange_client_id}\n"
                f"[{error_type}]: {error}"
            ),
        )


class OrdersStream(BaseStream):
    """Стрим ордеров: watch_orders → Redis cache + логирование."""

    def __init__(
        self,
        exchange_client_id: int,
        cache,
        trading_pair: TradingPair,
    ) -> None:
        self._exchange_client_id = exchange_client_id
        self._cache = cache
        self.trading_pair = trading_pair

    @property
    def key(self) -> tuple:
        return (
            self._exchange_client_id,
            type(self).__name__,
            self.trading_pair.symbol,
        )

    @property
    def exchange_client_id(self) -> int:
        return self._exchange_client_id

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        orders: list[ExchangeClientOrder] = await exchange_client.watch_orders(
            self.trading_pair
        )
        await self._cache.add_orders(
            exchange_client_id=self._exchange_client_id,
            orders=orders,
        )
        for order in orders:
            logger.info(
                f"WS ордер client_id={self._exchange_client_id} "
                f"{self.trading_pair.symbol} {order.side} "
                f"{order.amount} @ {order.price} "
                f"[{order.status}]"
            )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str) -> None:
        from telegram_bots.tasks import send_notification

        error_type = type(error).__name__
        logger.error(
            f"OrdersStream ошибка client_id={self._exchange_client_id}"
            f" [{error_type}]: {error}\n{tb}"
        )
        send_notification.delay(
            message=(
                f"WS ошибка client_id={self._exchange_client_id}\n"
                f"[{error_type}]: {error}"
            ),
        )


class CandleStream(BaseStream):
    """Стрим свечей: watch_ohlcv → Redis cache."""

    def __init__(
        self,
        exchange_client_id: int,
        cache,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        source_id: int = 0,
    ) -> None:
        self._exchange_client_id = exchange_client_id
        self._cache = cache
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.source_id = source_id

    @property
    def key(self) -> tuple:
        return (
            self._exchange_client_id,
            type(self).__name__,
            self.trading_pair.symbol,
            self.timeframe.value,
        )

    @property
    def exchange_client_id(self) -> int:
        return self._exchange_client_id

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        candles = await exchange_client.watch_ohlcv(
            self.trading_pair,
            self.timeframe,
        )
        for candle in candles:
            await self._cache.set_candle(
                exchange=exchange_client.exchange,
                trading_pair=self.trading_pair,
                timeframe=self.timeframe,
                candle=candle,
            )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str) -> None:
        from candle_sources.models import CandleSourceError
        from telegram_bots.tasks import send_notification

        error_type = type(error).__name__
        logger.error(
            f"CandleStream ошибка источника {self.source_id}"
            f" [{error_type}]: {error}\n{tb}"
        )
        CandleSourceError.objects.create(
            candle_source_id=self.source_id,
            message=str(error),
            type=error_type,
            traceback=tb,
        )
        send_notification.delay(
            message=(
                f"WebSocket ошибка для источника {self.source_id}\n"
                f"[{error_type}]: {error}"
            ),
        )


class OrderBookStream(BaseStream):
    """Стрим стакана: watch_order_book."""

    def __init__(
        self,
        exchange_client_id: int,
        trading_pair: TradingPair,
        limit: int = 20,
    ) -> None:
        self._exchange_client_id = exchange_client_id
        self.trading_pair = trading_pair
        self.limit = limit

    @property
    def key(self) -> tuple:
        return (
            self._exchange_client_id,
            type(self).__name__,
            self.trading_pair.symbol,
        )

    @property
    def exchange_client_id(self) -> int:
        return self._exchange_client_id

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        await exchange_client.watch_order_book(
            self.trading_pair,
            self.limit,
        )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str) -> None:
        from telegram_bots.tasks import send_notification

        error_type = type(error).__name__
        logger.error(
            f"OrderBookStream ошибка client_id={self._exchange_client_id}"
            f" [{error_type}]: {error}\n{tb}"
        )
        send_notification.delay(
            message=(
                f"WS ошибка client_id={self._exchange_client_id}\n"
                f"[{error_type}]: {error}"
            ),
        )
