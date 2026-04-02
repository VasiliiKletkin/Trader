"""WS-менеджеры: свечи, балансы, ордера."""

import asyncio
import contextlib
import traceback
from collections.abc import Awaitable, Callable

from asgiref.sync import sync_to_async
from django.conf import settings
from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceError, CandleSourceMode
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.streams import BaseStream
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from telegram_bots.tasks import send_notification

SYNC_INTERVAL = 60
MAX_BACKOFF = 60

StreamsLoader = Callable[[], Awaitable[dict[int, list[BaseStream]]]]


class CandleStreamManager:
    """Управляет WS-стримами свечей.

    Периодически загружает подписки из БД и запускает
    watch_ohlcv_for_symbols — один вызов на exchange_client.
    """

    def __init__(self, pool: ExchangeClientPool) -> None:
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
        self._running: dict[int, asyncio.Task] = {}
        self._subscriptions: dict[int, list[tuple[TradingPair, Timeframe]]] = {}
        self._source_ids: dict[int, list[int]] = {}

    async def start(self) -> None:
        """Загружает начальные подписки."""
        await self._load_subscriptions()

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Sync-loop: загрузка подписок + reconcile стримов."""
        self._shutdown_event = shutdown_event
        try:
            while not shutdown_event.is_set():
                await asyncio.sleep(SYNC_INTERVAL)
                try:
                    await self._load_subscriptions()
                    self._reconcile()
                except Exception as e:
                    logger.error(f"CandleStreamManager ошибка sync: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Останавливает все стримы."""
        for task in self._running.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._running.values())
        self._running.clear()

    # --- Private ---

    @sync_to_async
    def _load_subscriptions(self) -> None:
        subs: dict[int, list[tuple[TradingPair, Timeframe]]] = {}
        source_ids: dict[int, list[int]] = {}
        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "trading_pair",
        )
        for source in sources:
            cid = source.exchange_client_id
            domain_tp = source.trading_pair.instantiate(
                exchange=source.exchange_client.exchange,
            )
            subs.setdefault(cid, []).append((domain_tp, Timeframe(source.timeframe)))
            source_ids.setdefault(cid, []).append(source.pk)
        self._subscriptions = subs
        self._source_ids = source_ids

    def _reconcile(self) -> None:
        desired_ids = set(self._subscriptions.keys())

        for client_id in desired_ids:
            client = self._pool.get(client_id)
            if client is None:
                continue
            existing = self._running.get(client_id)
            if existing is not None and not existing.done():
                continue
            self._running[client_id] = asyncio.create_task(
                self._stream_loop(client_id),
            )

        removed = set(self._running) - desired_ids
        for client_id in removed:
            self._running.pop(client_id).cancel()

    async def _stream_loop(self, client_id: int) -> None:
        backoff = 1
        while not self._shutdown_event.is_set():
            client = self._pool.get(client_id)
            subs = self._subscriptions.get(client_id)
            if client is None or not subs:
                await asyncio.sleep(SYNC_INTERVAL)
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


class BalanceStreamManager:
    """Управляет WS-стримами балансов и ордеров.

    Периодически загружает стримы из БД и запускает их.
    Каждый BaseStream получает exchange_client из общего пула.
    """

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_streams: StreamsLoader,
        sync_interval: int = 60,
    ):
        self._pool = pool
        self._load_streams = load_streams
        self._sync_interval = sync_interval
        self._running: dict[tuple, asyncio.Task] = {}

    async def start(self) -> None:
        """Загружает начальные стримы."""
        await self._load_streams()

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Sync-loop: загрузка стримов + reconcile."""
        try:
            while not shutdown_event.is_set():
                await asyncio.sleep(self._sync_interval)
                try:
                    desired = await self._load_streams()
                    self._reconcile(desired, shutdown_event)
                except Exception as e:
                    logger.error(f"BalanceStreamManager ошибка sync: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Останавливает все стримы."""
        for task in self._running.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._running.values())
        self._running.clear()

    # --- Private ---

    def _reconcile(
        self,
        desired: dict[int, list[BaseStream]],
        shutdown_event: asyncio.Event,
    ) -> None:
        desired_keys: set[tuple] = set()

        for client_id, streams in desired.items():
            client = self._pool.get(client_id)
            if client is None:
                continue
            for stream in streams:
                key = (client_id, *stream.key)
                desired_keys.add(key)
                existing = self._running.get(key)
                if existing is not None and not existing.done():
                    continue
                self._running[key] = asyncio.create_task(
                    stream.run(
                        exchange_client=client,
                        shutdown_event=shutdown_event,
                    )
                )

        removed = set(self._running) - desired_keys
        for key in removed:
            self._running.pop(key).cancel()
