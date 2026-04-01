"""Менеджер WebSocket-стримов (балансы, ордера и т.д.)."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from loguru import logger

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.streams import BaseStream

StreamsLoader = Callable[[], Awaitable[dict[int, list[BaseStream]]]]


class StreamWorker:
    """Менеджер WebSocket-стримов.

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

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Запускает sync-loop. Вызывается как background task."""
        logger.info("StreamWorker запускается...")
        try:
            while not shutdown_event.is_set():
                try:
                    desired = await self._load_streams()
                    self._reconcile(desired, shutdown_event)
                except Exception as e:
                    logger.error(f"StreamWorker: ошибка sync: {e}")
                await asyncio.sleep(self._sync_interval)
        except asyncio.CancelledError:
            pass
        finally:
            await self._stop_all()
        logger.info("StreamWorker завершён.")

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
        if removed:
            logger.info(f"StreamWorker: -{len(removed)} стримов")

    async def _stop_all(self) -> None:
        for task in self._running.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._running.values())
        self._running.clear()
