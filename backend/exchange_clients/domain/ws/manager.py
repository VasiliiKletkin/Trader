import asyncio
import contextlib
import signal
from collections.abc import Callable

from loguru import logger

from exchange_clients.domain import AbstractExchangeClient
from exchange_clients.domain.ws.streams import BaseStream


class ExchangeConnection:
    """Одно WebSocket-соединение с биржей.

    Управляет lifecycle ccxt-клиента и запускает стримы.
    """

    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        streams: list[BaseStream],
    ):
        self.exchange_client = exchange_client
        self.streams = streams
        self._running: dict[tuple, asyncio.Task] = {}

    async def __aenter__(self) -> "ExchangeConnection":
        await self.exchange_client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        for task in self._running.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._running.values())
        self._running.clear()
        with contextlib.suppress(Exception):
            await self.exchange_client.__aexit__(*exc)

    def update_streams(
        self,
        streams: list[BaseStream],
        shutdown_event: asyncio.Event,
    ) -> None:
        """Обновляет стримы: добавляет новые, удаляет лишние."""
        new_keys = {s.key: s for s in streams}
        old_keys = set(self._running)

        # Удаляем убранные
        removed = old_keys - set(new_keys)
        for key in removed:
            self._running.pop(key).cancel()

        # Добавляем новые
        added = set(new_keys) - old_keys
        for key in added:
            self._running[key] = asyncio.create_task(
                new_keys[key].run(
                    exchange_client=self.exchange_client,
                    shutdown_event=shutdown_event,
                )
            )

        if added or removed:
            logger.info(
                f"+{len(added)} -{len(removed)} (всего {len(self._running)} стримов)"
            )


class StreamManager:
    """Менеджер WebSocket-соединений.

    Периодически загружает соединения из БД (load_connections),
    и управляет их lifecycle.
    """

    def __init__(
        self,
        load_connections: Callable,
        sync_interval: int = 60,
    ):
        self.load_connections = load_connections
        self.sync_interval = sync_interval
        self.shutdown_event = asyncio.Event()
        self._connections: dict[int, ExchangeConnection] = {}

    async def run(self) -> None:
        logger.info("StreamManager запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        sync_task = asyncio.create_task(self._sync_loop())

        await self.shutdown_event.wait()

        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task

        await self._close_all()

        logger.info("StreamManager завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения, останавливаем стримы...")
        self.shutdown_event.set()

    async def _sync_loop(self) -> None:
        while not self.shutdown_event.is_set():
            desired = await self.load_connections()
            await self._reconcile(desired)
            await asyncio.sleep(self.sync_interval)

    async def _reconcile(
        self,
        desired: dict[int, ExchangeConnection],
    ) -> None:
        await self._close_removed(desired)
        await self._open_new(desired)
        self._sync_streams(desired)

    async def _close_removed(
        self,
        desired: dict[int, ExchangeConnection],
    ) -> None:
        for cid in set(self._connections) - set(desired):
            conn = self._connections.pop(cid)
            logger.info(f"Закрываем соединение exchange_client_id={cid}")
            await conn.__aexit__(None, None, None)

    async def _open_new(
        self,
        desired: dict[int, ExchangeConnection],
    ) -> None:
        for cid, new_conn in desired.items():
            if cid not in self._connections:
                await new_conn.__aenter__()
                await asyncio.sleep(0.5)
                self._connections[cid] = new_conn
                logger.info(f"Открыто соединение exchange_client_id={cid}")

    def _sync_streams(
        self,
        desired: dict[int, ExchangeConnection],
    ) -> None:
        for cid, new_conn in desired.items():
            if cid in self._connections:
                self._connections[cid].update_streams(
                    new_conn.streams, self.shutdown_event
                )

    async def _close_all(self) -> None:
        for conn in self._connections.values():
            await conn.__aexit__(None, None, None)
        self._connections.clear()
