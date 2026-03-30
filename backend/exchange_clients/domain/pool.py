"""Пул persistent-соединений к биржам."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from loguru import logger

from exchange_clients.domain.base import AbstractExchangeClient

DEFAULT_SYNC_INTERVAL = 60
DEFAULT_CONNECT_DELAY = 0.5

ClientLoader = Callable[[], Awaitable[dict[int, AbstractExchangeClient]]]


class ExchangeClientPool:
    """Управляет жизненным циклом соединений к биржам."""

    def __init__(
        self,
        loader: ClientLoader,
        sync_interval: float = DEFAULT_SYNC_INTERVAL,
        connect_delay: float = DEFAULT_CONNECT_DELAY,
    ) -> None:
        self._clients: dict[int, AbstractExchangeClient] = {}
        self._loader: ClientLoader = loader
        self._sync_interval: float = sync_interval
        self._connect_delay: float = connect_delay

    def get_client(self, client_id: int) -> AbstractExchangeClient | None:
        return self._clients.get(client_id)

    async def sync_loop(self, shutdown_event: asyncio.Event) -> None:
        """Периодически загружает клиентов из БД."""
        while not shutdown_event.is_set():
            try:
                desired: dict[int, AbstractExchangeClient] = await self._loader()
                await self._reconcile(desired=desired)
            except Exception as e:
                logger.error(f"ExchangeClientPool: ошибка sync: {e}")
            await asyncio.sleep(self._sync_interval)

    async def close(self) -> None:
        """Закрывает все соединения."""
        await self._close_clients(client_ids=set(self._clients))

    async def _reconcile(
        self,
        desired: dict[int, AbstractExchangeClient],
    ) -> None:
        """Добавляет новых и удаляет неактивных клиентов."""
        removed: set[int] = set(self._clients) - set(desired)
        await self._close_clients(client_ids=removed)

        for cid, client in desired.items():
            if cid not in self._clients:
                await self._open_client(client_id=cid, client=client)

    async def _open_client(
        self,
        client_id: int,
        client: AbstractExchangeClient,
    ) -> None:
        try:
            await client.__aenter__()
            self._clients[client_id] = client
            logger.info(f"ExchangeClientPool: открыт клиент {client_id}")
            await asyncio.sleep(self._connect_delay)
        except Exception as e:
            logger.error(f"ExchangeClientPool: ошибка подключения {client_id}: {e}")

    async def _close_clients(self, client_ids: set[int]) -> None:
        for cid in client_ids:
            client: AbstractExchangeClient | None = self._clients.pop(cid, None)
            if client is None:
                continue
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
            logger.info(f"ExchangeClientPool: закрыт клиент {cid}")
