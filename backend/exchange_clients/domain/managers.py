"""Менеджеры: пул соединений и WS-стримы."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import NamedTuple

from loguru import logger

from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.streams import BaseStream

DEFAULT_SYNC_INTERVAL = 60


class ClientEntry(NamedTuple):
    client: AbstractExchangeClient
    updated_at: datetime


ClientLoader = Callable[[], Awaitable[dict[int, ClientEntry]]]
StreamsLoader = Callable[[], Awaitable[dict[tuple, BaseStream]]]


class ExchangeClientPool:
    """Управляет жизненным циклом соединений к биржам.

    Периодически загружает клиентов из БД и синхронизирует пул:
    - добавляет новых клиентов
    - удаляет деактивированных
    - пересоздаёт изменённых (по updated_at)
    """

    def __init__(
        self,
        loader: ClientLoader,
        sync_interval: float = DEFAULT_SYNC_INTERVAL,
    ) -> None:
        self._clients: dict[int, ClientEntry] = {}
        self._loader = loader
        self._sync_interval = sync_interval

    def get(self, client_id: int) -> AbstractExchangeClient | None:
        entry = self._clients.get(client_id)
        return entry.client if entry else None

    async def start(self) -> None:
        """Первичная загрузка клиентов."""
        desired = await self._loader()
        await self._reconcile(desired)

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Периодически синхронизирует пул с БД."""
        while not shutdown_event.is_set():
            await asyncio.sleep(self._sync_interval)
            try:
                desired = await self._loader()
                await self._reconcile(desired)
            except Exception as e:
                logger.error(f"ExchangeClientPool ошибка sync: {e}")

    async def stop(self) -> None:
        """Закрывает все соединения."""
        for client_id in list(self._clients):
            await self._disconnect(client_id)

    async def _reconcile(self, desired: dict[int, ClientEntry]) -> None:
        current_ids = set(self._clients)
        desired_ids = set(desired)

        for client_id in current_ids - desired_ids:
            await self._disconnect(client_id)

        for client_id in desired_ids - current_ids:
            await self._connect(client_id, desired[client_id])

        for client_id in current_ids & desired_ids:
            if self._clients[client_id].updated_at != desired[client_id].updated_at:
                await self._disconnect(client_id)
                await self._connect(client_id, desired[client_id])

    async def _connect(self, client_id: int, entry: ClientEntry) -> None:
        try:
            await entry.client.__aenter__()
            self._clients[client_id] = entry
            logger.info(f"ExchangeClientPool подключён {client_id}")
        except Exception as e:
            logger.error(f"ExchangeClientPool ошибка подключения {client_id}: {e}")

    async def _disconnect(self, client_id: int) -> None:
        entry = self._clients.pop(client_id, None)
        if entry is None:
            return
        try:
            await entry.client.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"ExchangeClientPool ошибка отключения {client_id}: {e}")
        logger.info(f"ExchangeClientPool отключён {client_id}")


class StreamManager:
    """Менеджер WS-стримов.

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
        self._tasks: dict[tuple, asyncio.Task] = {}

    async def start(self) -> None:
        await self._load_streams()
        logger.info("StreamManager загружен")

    async def run(self, shutdown_event: asyncio.Event) -> None:
        desired = await self._load_streams()
        await self._reconcile(desired, shutdown_event)
        logger.info(f"StreamManager запущен ({len(self._tasks)} стримов)")
        while not shutdown_event.is_set():
            await asyncio.sleep(self._sync_interval)
            try:
                desired = await self._load_streams()
                await self._reconcile(desired, shutdown_event)
            except Exception as e:
                logger.error(f"StreamManager ошибка sync: {e}")

    async def stop(self) -> None:
        count = len(self._tasks)
        for key in list(self._tasks):
            await self._stop(key)
        logger.info(f"StreamManager остановлен ({count} стримов)")

    async def _reconcile(
        self,
        desired: dict[tuple, BaseStream],
        shutdown_event: asyncio.Event,
    ) -> None:
        current_keys = set(self._tasks)
        desired_keys = set(desired)

        for key in current_keys - desired_keys:
            await self._stop(key)

        for key in desired_keys - current_keys:
            self._start(desired[key], shutdown_event)

        for key in current_keys & desired_keys:
            if self._tasks[key].done():
                self._start(desired[key], shutdown_event)

    def _start(
        self,
        stream: BaseStream,
        shutdown_event: asyncio.Event,
    ) -> None:
        client = self._pool.get(stream.exchange_client_id)
        if client is None:
            logger.warning(
                f"StreamManager клиент {stream.exchange_client_id} не найден в пуле"
            )
            self._tasks.pop(stream.key, None)
            return
        self._tasks[stream.key] = asyncio.create_task(
            stream.run(exchange_client=client, shutdown_event=shutdown_event),
        )

    async def _stop(self, key: tuple) -> None:
        task = self._tasks.pop(key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"StreamManager ошибка остановки стрима {key}: {e}")
