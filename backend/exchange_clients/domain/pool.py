"""Пул persistent-соединений к биржам."""

import asyncio
import contextlib
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
        self._clients: dict[int, AbstractExchangeClient] = {}
        self._updated_at: dict[int, datetime] = {}
        self._loader = loader
        self._sync_interval = sync_interval

    def get(self, client_id: int) -> AbstractExchangeClient | None:
        return self._clients.get(client_id)

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Периодически синхронизирует пул с БД."""
        while not shutdown_event.is_set():
            try:
                desired = await self._loader()
                await self._reconcile(desired)
            except Exception as e:
                logger.error(f"ExchangeClientPool: ошибка sync: {e}")
            await asyncio.sleep(self._sync_interval)

    async def close(self) -> None:
        """Закрывает все соединения."""
        for client_id in list(self._clients):
            await self._disconnect(client_id)

    async def _reconcile(self, desired: dict[int, ClientEntry]) -> None:
        current_ids = set(self._clients)
        desired_ids = set(desired)

        for client_id in current_ids - desired_ids:
            await self._disconnect(client_id)

        for client_id in current_ids & desired_ids:
            _, updated_at = desired[client_id]
            if self._updated_at.get(client_id) != updated_at:
                logger.info(f"ExchangeClientPool: конфигурация {client_id} изменилась")
                await self._disconnect(client_id)

        for client_id, (client, updated_at) in desired.items():
            if client_id not in self._clients:
                await self._connect(client_id, client, updated_at)

    async def _connect(
        self,
        client_id: int,
        client: AbstractExchangeClient,
        updated_at: datetime,
    ) -> None:
        try:
            await client.__aenter__()
            self._clients[client_id] = client
            self._updated_at[client_id] = updated_at
            logger.info(f"ExchangeClientPool: подключён {client_id}")
        except Exception as e:
            logger.error(f"ExchangeClientPool: ошибка подключения {client_id}: {e}")

    async def _disconnect(self, client_id: int) -> None:
        client = self._clients.pop(client_id, None)
        self._updated_at.pop(client_id, None)
        if client is None:
            return
        with contextlib.suppress(Exception):
            await client.__aexit__(None, None, None)
        logger.info(f"ExchangeClientPool: отключён {client_id}")
