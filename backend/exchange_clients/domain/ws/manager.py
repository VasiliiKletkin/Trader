import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable

from loguru import logger

from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.streams import BaseStream

StreamsLoader = Callable[[], Awaitable[dict[int, list[BaseStream]]]]


class StreamWorker:
    """Менеджер WebSocket-стримов.

    Использует ExchangeClientPool для управления соединениями.
    Периодически загружает конфигурацию стримов из БД и запускает их.
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
        self._shutdown_event = asyncio.Event()
        self._running: dict[tuple, asyncio.Task] = {}

    async def run(self) -> None:
        logger.info("StreamWorker запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        pool_task = asyncio.create_task(self._pool.run(self._shutdown_event))
        sync_task = asyncio.create_task(self._sync_loop())

        await self._shutdown_event.wait()

        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task

        pool_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pool_task

        await self._stop_all()
        await self._pool.close()

        logger.info("StreamWorker завершён.")

    async def _sync_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                desired: dict[int, list[BaseStream]] = await self._load_streams()
                self._reconcile(desired)
            except Exception as e:
                logger.error(f"StreamWorker: ошибка sync: {e}")
            await asyncio.sleep(self._sync_interval)

    def _reconcile(self, desired: dict[int, list[BaseStream]]) -> None:
        """Запускает новые стримы, останавливает убранные."""
        desired_keys: set[tuple] = set()
        for client_id, streams in desired.items():
            client = self._pool.get(client_id)
            if client is None:
                continue
            for stream in streams:
                key = (client_id, *stream.key)
                desired_keys.add(key)
                if key not in self._running:
                    self._running[key] = asyncio.create_task(
                        stream.run(
                            exchange_client=client,
                            shutdown_event=self._shutdown_event,
                        )
                    )

        # Останавливаем убранные
        removed = set(self._running) - desired_keys
        for key in removed:
            self._running.pop(key).cancel()

        if removed:
            logger.info(f"StreamWorker: -{len(removed)} стримов")

    async def _stop_all(self) -> None:
        for task in self._running.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._running.values())
        self._running.clear()


class ExchangeConnection:
    """Устаревший класс для обратной совместимости с run_ws_traders/run_ws_candle_sources."""

    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        streams: list[BaseStream],
    ):
        self.exchange_client = exchange_client
        self.streams = streams
