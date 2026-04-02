"""Менеджеры: пул соединений и WS-стримы."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from loguru import logger

from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.streams import BaseStream

DEFAULT_SYNC_INTERVAL = 60

ClientEntry = tuple[AbstractExchangeClient, datetime]
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
        return entry[0] if entry else None

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
                logger.error(f"ExchangeClientPool: ошибка sync: {e}")

    async def stop(self) -> None:
        """Закрывает все соединения."""
        for client_id in list(self._clients):
            await self._disconnect(client_id)

    async def _reconcile(self, desired: dict[int, ClientEntry]) -> None:
        current_ids = set(self._clients)
        desired_ids = set(desired)

        # Отключить удалённых клиентов
        for client_id in current_ids - desired_ids:
            await self._disconnect(client_id)

        # Переподключить изменённых клиентов
        for client_id in current_ids & desired_ids:
            client, updated_at = desired[client_id]
            _, current_updated_at = self._clients[client_id]
            if current_updated_at != updated_at:
                logger.info(f"ExchangeClientPool: конфигурация {client_id} изменилась")
                await self._disconnect(client_id)
                await self._connect(client_id, client, updated_at)

        # Подключить новых клиентов
        for client_id in desired_ids - current_ids:
            client, updated_at = desired[client_id]
            await self._connect(client_id, client, updated_at)

    async def _connect(
        self,
        client_id: int,
        client: AbstractExchangeClient,
        updated_at: datetime,
    ) -> None:
        try:
            await client.__aenter__()
            self._clients[client_id] = (client, updated_at)
            logger.info(f"ExchangeClientPool: подключён {client_id}")
        except Exception as e:
            logger.error(f"ExchangeClientPool: ошибка подключения {client_id}: {e}")

    async def _disconnect(self, client_id: int) -> None:
        entry = self._clients.pop(client_id, None)
        if entry is None:
            return
        client, _ = entry
        try:
            await client.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"ExchangeClientPool: ошибка отключения {client_id}: {e}")
        logger.info(f"ExchangeClientPool: отключён {client_id}")


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
        self._streams: dict[tuple, asyncio.Task] = {}

    @property
    def _name(self) -> str:
        return type(self).__name__

    async def start(self) -> None:
        """Проверяет загрузку стримов из БД."""
        await self._load_streams()
        logger.info(f"{self._name} загружен")

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Reconcile + периодическая синхронизация с БД."""
        desired = await self._load_streams()
        await self._reconcile(desired, shutdown_event)
        logger.info(f"{self._name} запущен ({len(self._streams)} стримов)")
        while not shutdown_event.is_set():
            await asyncio.sleep(self._sync_interval)
            try:
                desired = await self._load_streams()
                await self._reconcile(desired, shutdown_event)
            except Exception as e:
                logger.error(f"{self._name} ошибка sync: {e}")

    async def stop(self) -> None:
        """Останавливает все стримы."""
        count = len(self._streams)
        for key in list(self._streams):
            await self._stop_stream(key)
        logger.info(f"{self._name} остановлен ({count} стримов)")

    # --- Private ---

    async def _reconcile(
        self,
        desired: dict[tuple, BaseStream],
        shutdown_event: asyncio.Event,
    ) -> None:
        current_keys = set(self._streams)
        desired_keys = set(desired)

        # Остановить удалённые стримы
        for key in current_keys - desired_keys:
            await self._stop_stream(key)

        # Запустить новые стримы
        for key in desired_keys - current_keys:
            self._start_stream(desired[key], shutdown_event)

        # Перезапустить упавшие стримы
        for key in current_keys & desired_keys:
            task = self._streams[key]
            if task.done():
                self._start_stream(desired[key], shutdown_event)

    def _start_stream(
        self,
        stream: BaseStream,
        shutdown_event: asyncio.Event,
    ) -> None:
        client = self._pool.get(stream.exchange_client_id)
        if client is None:
            logger.warning(f"{self._name} клиент {stream.exchange_client_id} не найден")
            return
        self._streams[stream.key] = asyncio.create_task(
            stream.run(exchange_client=client, shutdown_event=shutdown_event),
        )
        logger.debug(f"{self._name} +стрим {stream.key}")

    async def _stop_stream(self, key: tuple) -> None:
        task = self._streams.pop(key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"{self._name} ошибка остановки стрима {key}: {e}")
        logger.debug(f"{self._name} -стрим {key}")


class CandleStreamManager(StreamManager):
    """Менеджер WS-стримов свечей."""


class BalanceStreamManager(StreamManager):
    """Менеджер WS-стримов балансов."""


class OrderStreamManager(StreamManager):
    """Менеджер WS-стримов ордеров."""
