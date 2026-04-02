"""WS-менеджеры: свечи, балансы, ордера."""

import asyncio
import contextlib
import traceback
from collections.abc import Awaitable, Callable

from asgiref.sync import sync_to_async
from django.conf import settings
from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSourceError
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.streams import BaseStream
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from telegram_bots.tasks import send_notification

DEFAULT_SYNC_INTERVAL = 60
MAX_BACKOFF = 60

StreamsLoader = Callable[[], Awaitable[dict[int, list[BaseStream]]]]
CandleSubscriptionsLoader = Callable[
    [],
    Awaitable[
        tuple[
            dict[int, list[tuple[TradingPair, Timeframe]]],
            dict[int, list[int]],
        ]
    ],
]


class CandleStreamManager:
    """Управляет WS-стримами свечей.

    Периодически загружает подписки и запускает
    watch_ohlcv_for_symbols — один вызов на exchange_client.
    """

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_subscriptions: CandleSubscriptionsLoader,
        sync_interval: int = DEFAULT_SYNC_INTERVAL,
    ) -> None:
        redis_settings = settings.REDIS
        self._candle_cache = CandleRedisCache(
            host=str(redis_settings["HOST"]),
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=str(redis_settings["PASSWORD"])
            if redis_settings.get("PASSWORD")
            else None,
        )
        self._pool = pool
        self._load_subscriptions = load_subscriptions
        self._sync_interval = sync_interval
        self._tasks: dict[int, asyncio.Task] = {}
        self._subscriptions: dict[int, list[tuple[TradingPair, Timeframe]]] = {}
        self._source_ids: dict[int, list[int]] = {}

    async def start(self) -> None:
        """Первичная загрузка подписок."""
        self._subscriptions, self._source_ids = await self._load_subscriptions()

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Reconcile + периодическая синхронизация с БД."""
        self._shutdown_event = shutdown_event
        self._reconcile()
        try:
            while not shutdown_event.is_set():
                await asyncio.sleep(self._sync_interval)
                try:
                    (
                        self._subscriptions,
                        self._source_ids,
                    ) = await self._load_subscriptions()
                    self._reconcile()
                except Exception as e:
                    logger.error(f"CandleStreamManager ошибка sync: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Останавливает все стримы."""
        for task in list(self._tasks.values()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

    # --- Private ---

    def _reconcile(self) -> None:
        desired_ids = set(self._subscriptions.keys())

        for client_id in desired_ids:
            client = self._pool.get(client_id)
            if client is None:
                continue
            existing = self._tasks.get(client_id)
            if existing is not None and not existing.done():
                continue
            self._tasks[client_id] = asyncio.create_task(
                self._stream_loop(client_id),
            )

        removed = set(self._tasks) - desired_ids
        for client_id in removed:
            self._tasks.pop(client_id).cancel()

    async def _stream_loop(self, client_id: int) -> None:
        backoff = 1
        while not self._shutdown_event.is_set():
            client = self._pool.get(client_id)
            subs = self._subscriptions.get(client_id)
            if client is None or not subs:
                await asyncio.sleep(self._sync_interval)
                continue
            try:
                result = await client.watch_ohlcv_for_symbols(subs)
                backoff = 1
                for trading_pair, timeframes in result.items():
                    for timeframe, candles in timeframes.items():
                        for candle in candles:
                            await self._on_candle(
                                exchange=client.exchange,
                                trading_pair=trading_pair,
                                timeframe=timeframe,
                                candle=candle,
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                tb = traceback.format_exc()
                source_ids = self._source_ids.get(client_id, [])
                await self._on_error(
                    error=e,
                    tb=tb,
                    source_id=source_ids[0] if source_ids else 0,
                )
                await asyncio.sleep(min(backoff, MAX_BACKOFF))
                backoff = min(backoff * 2, MAX_BACKOFF)

    async def _on_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        candle: Candle,
    ) -> None:
        await self._candle_cache.set_candle(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=timeframe,
            candle=candle,
        )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str, source_id: int) -> None:
        error_type = type(error).__name__
        logger.error(
            f"CandleStreamManager ошибка источника {source_id}"
            f" [{error_type}]: {error}\n{tb}"
        )
        CandleSourceError.objects.create(
            candle_source_id=source_id,
            message=str(error),
            type=error_type,
            traceback=tb,
        )
        send_notification.delay(
            message=(
                f"WebSocket ошибка для источника {source_id}\n[{error_type}]: {error}"
            ),
        )


class StreamManager:
    """Базовый менеджер WS-стримов.

    Периодически загружает стримы из БД и запускает их.
    Каждый BaseStream получает exchange_client из общего пула.
    """

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_streams: StreamsLoader,
        sync_interval: int = DEFAULT_SYNC_INTERVAL,
    ):
        self._pool = pool
        self._load_streams = load_streams
        self._sync_interval = sync_interval
        self._desired: dict[int, list[BaseStream]] = {}
        self._tasks: dict[tuple, asyncio.Task] = {}

    async def start(self) -> None:
        """Первичная загрузка стримов из БД."""
        self._desired = await self._load_streams()

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Reconcile + периодическая синхронизация с БД."""
        name = type(self).__name__
        self._reconcile(self._desired, shutdown_event)
        try:
            while not shutdown_event.is_set():
                await asyncio.sleep(self._sync_interval)
                try:
                    desired = await self._load_streams()
                    self._reconcile(desired, shutdown_event)
                except Exception as e:
                    logger.error(f"{name} ошибка sync: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Останавливает все стримы."""
        for task in list(self._tasks.values()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

    # --- Private ---

    def _reconcile(
        self,
        desired: dict[int, list[BaseStream]],
        shutdown_event: asyncio.Event,
    ) -> None:
        desired_tasks: dict[tuple, tuple[BaseStream, int]] = {}
        for client_id, streams in desired.items():
            for stream in streams:
                desired_tasks[(client_id, *stream.key)] = (stream, client_id)

        # Остановить стримы, которых больше нет
        for key in set(self._tasks) - set(desired_tasks):
            self._tasks.pop(key).cancel()

        # Запустить новые или упавшие стримы
        for key, (stream, client_id) in desired_tasks.items():
            existing = self._tasks.get(key)
            if existing is not None and not existing.done():
                continue
            client = self._pool.get(client_id)
            if client is None:
                continue
            self._tasks[key] = asyncio.create_task(
                stream.run(
                    exchange_client=client,
                    shutdown_event=shutdown_event,
                ),
            )


class BalanceStreamManager(StreamManager):
    """Менеджер WS-стримов балансов."""


class OrderStreamManager(StreamManager):
    """Менеджер WS-стримов ордеров."""
