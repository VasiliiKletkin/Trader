"""Пул persistent-соединений к биржам."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from loguru import logger

from exchange_clients.domain.base import AbstractExchangeClient

DEFAULT_SYNC_INTERVAL = 60

ClientEntry = tuple[AbstractExchangeClient, datetime]
ClientLoader = Callable[[], Awaitable[dict[int, ClientEntry]]]


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

        for client_id in current_ids - desired_ids:
            await self._disconnect(client_id)

        for client_id in current_ids & desired_ids:
            client, updated_at = desired[client_id]
            _, current_updated_at = self._clients[client_id]
            if current_updated_at != updated_at:
                logger.info(f"ExchangeClientPool: конфигурация {client_id} изменилась")
                await self._disconnect(client_id)
                await self._connect(client_id, client, updated_at)

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
