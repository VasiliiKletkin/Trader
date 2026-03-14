import asyncio
import contextlib
import signal
from collections.abc import Callable, Coroutine
from dataclasses import dataclass

from loguru import logger

from candle_sources.domain.candle_sources import CandleSource
from candle_sources.domain.ws.streams import OHLCVStream
from exchange_clients.domain import AbstractExchangeClient


@dataclass
class Subscription:
    """Подписка на стрим с привязкой к exchange_client_id."""

    source: CandleSource
    exchange_client_id: int


class ExchangeConnection:
    """
    Одно WebSocket-соединение с биржей для получения свечей.

    Управляет lifecycle клиента и OHLCV-стримами.
    Принимает желаемое состояние подписок через update_subscriptions()
    и сам выполняет reconcile.
    """

    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        on_candle: Callable[..., Coroutine],
        on_error: Callable[..., Coroutine],
        shutdown_event: asyncio.Event,
    ):
        self.exchange_client = exchange_client
        self.on_candle = on_candle
        self.on_error = on_error
        self.shutdown_event = shutdown_event
        self._streams: dict[int, asyncio.Task] = {}

    @property
    def is_empty(self) -> bool:
        return len(self._streams) == 0

    async def connect(self) -> None:
        await self.exchange_client.__aenter__()

    async def close(self) -> None:
        for task in self._streams.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._streams.values())
        self._streams.clear()
        with contextlib.suppress(Exception):
            await self.exchange_client.__aexit__(None, None, None)

    def update_subscriptions(self, sources: dict[int, CandleSource]) -> None:
        """Принимает желаемое состояние подписок, сам добавляет/удаляет."""
        desired = set(sources.keys())
        current = set(self._streams.keys())

        for source_id in current - desired:
            task = self._streams.pop(source_id)
            task.cancel()
            logger.info(f"Удалён стрим source_id={source_id}")

        for source_id in desired - current:
            source = sources[source_id]
            stream = OHLCVStream(
                exchange_client=self.exchange_client,
                trading_pair=source.trading_pair,
                timeframe=source.timeframe,
                on_candle=self.on_candle,
                on_error=self.on_error,
                shutdown_event=self.shutdown_event,
                source_id=source_id,
            )
            task = asyncio.create_task(
                stream.run(),
                name=(f"ohlcv:{source.trading_pair.symbol}:{source.timeframe.value}"),
            )
            self._streams[source_id] = task
            logger.info(
                f"Добавлен стрим source_id={source_id} "
                f"{source.trading_pair.symbol}:{source.timeframe.value}"
            )


class CandleStreamManager:
    """
    Менеджер WebSocket-соединений для получения свечей.

    Двухуровневая архитектура:
    - Manager управляет ExchangeConnection (одно на exchange_client_id)
    - ExchangeConnection управляет OHLCV-стримами

    Периодически (каждые sync_interval секунд) загружает подписки из БД
    и добавляет/удаляет соединения и стримы без перезапуска.
    """

    def __init__(
        self,
        load_subscriptions: Callable[..., Coroutine],
        on_candle: Callable[..., Coroutine],
        on_error: Callable[..., Coroutine],
        sync_interval: int = 30,
    ):
        self.load_subscriptions = load_subscriptions
        self.on_candle = on_candle
        self.on_error = on_error
        self.sync_interval = sync_interval
        self.shutdown_event = asyncio.Event()

        # exchange_client_id → ExchangeConnection
        self._connections: dict[int, ExchangeConnection] = {}

    async def run(self) -> None:
        logger.info("CandleStreamManager запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        subscriptions = await self.load_subscriptions()
        await self._reconcile(subscriptions)

        if not self._connections:
            logger.warning("Нет активных WS-подписок на свечи.")

        sync_task = asyncio.create_task(self._sync_loop())

        await self.shutdown_event.wait()

        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task

        for conn in self._connections.values():
            await conn.close()

        logger.info("CandleStreamManager завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения, останавливаем стримы...")
        self.shutdown_event.set()

    async def _sync_loop(self) -> None:
        """Периодически загружает подписки из БД и синхронизирует."""
        while not self.shutdown_event.is_set():
            await asyncio.sleep(self.sync_interval)
            subscriptions = await self.load_subscriptions()
            await self._reconcile(subscriptions)

    async def _reconcile(self, subscriptions: list[Subscription]) -> None:
        """Группирует подписки по exchange_client_id, обновляет соединения."""
        groups: dict[int, dict[int, CandleSource]] = {}
        for sub in subscriptions:
            sources = groups.setdefault(sub.exchange_client_id, {})
            sources[sub.source.source_id] = sub.source

        new_client_ids = set(groups.keys())
        current_client_ids = set(self._connections.keys())

        for client_id in current_client_ids - new_client_ids:
            conn = self._connections.pop(client_id)
            logger.info(f"Закрываем соединение exchange_client_id={client_id}")
            await conn.close()

        for client_id, sources in groups.items():
            if client_id in self._connections:
                self._connections[client_id].update_subscriptions(sources)
            else:
                exchange_client = next(iter(sources.values())).exchange_client
                conn = ExchangeConnection(
                    exchange_client=exchange_client,
                    on_candle=self.on_candle,
                    on_error=self.on_error,
                    shutdown_event=self.shutdown_event,
                )
                await conn.connect()
                await asyncio.sleep(0.5)
                self._connections[client_id] = conn
                logger.info(f"Открыто соединение exchange_client_id={client_id}")
                conn.update_subscriptions(sources)

            if client_id in self._connections and self._connections[client_id].is_empty:
                conn = self._connections.pop(client_id)
                logger.info(
                    f"Закрываем соединение exchange_client_id={client_id} (нет стримов)"
                )
                await conn.close()
