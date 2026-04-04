"""Менеджеры: пул соединений и WS-стримы."""

import asyncio
from abc import ABC, abstractmethod
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


class BaseManager(ABC):
    """Базовый менеджер с lifecycle start/run/stop и interruptible sleep."""

    def __init__(self, sync_interval: float = DEFAULT_SYNC_INTERVAL) -> None:
        self._sync_interval = sync_interval

    async def _interruptible_sleep(self, event: asyncio.Event, timeout: float) -> bool:
        """Спит timeout секунд, прерывается если event установлен.

        Возвращает True если shutdown, False если таймаут.
        """
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def run(self, shutdown_event: asyncio.Event) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError


class ExchangeClientPool(BaseManager):
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
        super().__init__(sync_interval=sync_interval)
        self._clients: dict[int, ClientEntry] = {}
        self._loader = loader

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
            if await self._interruptible_sleep(shutdown_event, self._sync_interval):
                break
            try:
                desired = await self._loader()
                await self._reconcile(desired)
            except Exception as e:
                logger.error(
                    f"ExchangeClientPool ошибка sync [{type(e).__name__}]: {e}"
                )

    async def stop(self) -> None:
        """Закрывает все соединения."""
        await asyncio.gather(*(self._disconnect(cid) for cid in list(self._clients)))

    async def _reconcile(self, desired: dict[int, ClientEntry]) -> None:
        current_ids = set(self._clients)
        desired_ids = set(desired)

        remove_ids = current_ids - desired_ids
        add_ids = desired_ids - current_ids
        update_ids = {
            cid
            for cid in current_ids & desired_ids
            if self._clients[cid].updated_at != desired[cid].updated_at
        }

        for client_id in remove_ids:
            await self._disconnect(client_id)

        for client_id in add_ids:
            await self._connect(client_id, desired[client_id])

        for client_id in update_ids:
            await self._disconnect(client_id)
            await self._connect(client_id, desired[client_id])

        if remove_ids or add_ids or update_ids:
            logger.info(
                f"ExchangeClientPool reconcile: "
                f"+{len(add_ids)} -{len(remove_ids)} ~{len(update_ids)}"
            )

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


class StreamManager(BaseManager):
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
        super().__init__(sync_interval=sync_interval)
        self._pool = pool
        self._load_streams = load_streams
        self._tasks: dict[tuple, asyncio.Task] = {}

    async def start(self) -> None:
        await self._load_streams()
        logger.info("StreamManager загружен")

    async def run(self, shutdown_event: asyncio.Event) -> None:
        desired = await self._load_streams()
        await self._reconcile(desired, shutdown_event)
        logger.info(f"StreamManager запущен ({len(self._tasks)} стримов)")
        while not shutdown_event.is_set():
            if await self._interruptible_sleep(shutdown_event, self._sync_interval):
                break
            try:
                desired = await self._load_streams()
                await self._reconcile(desired, shutdown_event)
            except Exception as e:
                logger.error(f"StreamManager ошибка sync [{type(e).__name__}]: {e}")

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

        remove_keys = current_keys - desired_keys
        add_keys = desired_keys - current_keys
        restart_keys = {
            key for key in current_keys & desired_keys if self._tasks[key].done()
        }

        for key in remove_keys:
            await self._stop(key)

        for key in add_keys:
            self._start(desired[key], shutdown_event)

        for key in restart_keys:
            self._start(desired[key], shutdown_event)

        if remove_keys or add_keys or restart_keys:
            logger.info(
                f"StreamManager reconcile: "
                f"+{len(add_keys)} -{len(remove_keys)} ~{len(restart_keys)}"
            )

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
        logger.info(f"StreamManager стрим подключён {stream.key}")

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
        logger.info(f"StreamManager стрим отключён {key}")
