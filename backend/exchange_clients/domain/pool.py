"""Пул persistent-соединений к биржам."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from loguru import logger

from exchange_clients.domain.base import AbstractExchangeClient

SYNC_INTERVAL = 60 * 10

ClientLoader = Callable[[], Awaitable[dict[int, AbstractExchangeClient]]]


class ExchangeClientPool:
    """Управляет жизненным циклом соединений к биржам."""

    def __init__(self, loader: ClientLoader) -> None:
        self._clients: dict[int, AbstractExchangeClient] = {}
        self._loader = loader

    def get_client(self, client_id: int) -> AbstractExchangeClient | None:
        return self._clients.get(client_id)

    async def sync_loop(self, shutdown_event: asyncio.Event) -> None:
        """Периодически загружает клиентов из БД."""
        while not shutdown_event.is_set():
            try:
                desired = await self._loader()
                await self._reconcile(desired)
            except Exception as e:
                logger.error(f"Exchange worker: ошибка sync: {e}")
            await asyncio.sleep(SYNC_INTERVAL)

    async def _reconcile(self, desired: dict[int, AbstractExchangeClient]) -> None:
        """Добавляет новых и удаляет неактивных клиентов."""
        for cid in set(self._clients) - set(desired):
            client = self._clients.pop(cid)
            logger.info(f"Exchange worker: закрываю клиент {cid}")
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)

        for cid, client in desired.items():
            if cid not in self._clients:
                await client.__aenter__()
                self._clients[cid] = client
                logger.info(f"Exchange worker: открыт клиент {cid}")
                await asyncio.sleep(0.5)

    async def close(self) -> None:
        """Закрывает все соединения."""
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
        self._clients.clear()
