import asyncio
import contextlib
import signal
from collections.abc import Callable, Coroutine

from loguru import logger

from candle_sources.domain.ws.streams import BalanceStream, OrdersStream
from exchange_clients.domain import AbstractExchangeClient


class ExchangeClientConnection:
    """
    Одно WebSocket-соединение с биржей для приватных данных.

    Управляет стримами баланса и ордеров для одного exchange_client.
    """

    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        exchange_client_id: int,
        on_balance: Callable[..., Coroutine],
        on_orders: Callable[..., Coroutine],
        on_error: Callable[..., Coroutine],
        shutdown_event: asyncio.Event,
    ):
        self.exchange_client = exchange_client
        self.exchange_client_id = exchange_client_id
        self.on_balance = on_balance
        self.on_orders = on_orders
        self.on_error = on_error
        self.shutdown_event = shutdown_event
        self._balance_task: asyncio.Task | None = None
        self._orders_task: asyncio.Task | None = None

    async def connect(self) -> None:
        await self.exchange_client.__aenter__()
        client_id = self.exchange_client_id

        self._balance_task = asyncio.create_task(
            BalanceStream(
                exchange_client=self.exchange_client,
                on_balance=self.on_balance,
                on_error=self.on_error,
                shutdown_event=self.shutdown_event,
                exchange_client_id=client_id,
            ).run(),
            name=f"balance:{client_id}",
        )
        self._orders_task = asyncio.create_task(
            OrdersStream(
                exchange_client=self.exchange_client,
                on_orders=self.on_orders,
                on_error=self.on_error,
                shutdown_event=self.shutdown_event,
                exchange_client_id=client_id,
            ).run(),
            name=f"orders:{client_id}",
        )
        logger.info(f"Запущены стримы баланса и ордеров exchange_client_id={client_id}")

    async def close(self) -> None:
        tasks = [t for t in (self._balance_task, self._orders_task) if t]
        for task in tasks:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks)
        self._balance_task = None
        self._orders_task = None
        with contextlib.suppress(Exception):
            await self.exchange_client.__aexit__(None, None, None)


class ExchangeClientStreamManager:
    """
    Менеджер WebSocket-соединений для приватных данных клиентов бирж.

    Управляет ExchangeClientConnection (одно на exchange_client_id).
    Каждое соединение отслеживает баланс и ордера.

    Периодически (каждые sync_interval секунд) загружает клиентов из БД
    и добавляет/удаляет соединения без перезапуска.
    """

    def __init__(
        self,
        load_clients: Callable[..., Coroutine],
        on_balance: Callable[..., Coroutine],
        on_orders: Callable[..., Coroutine],
        on_error: Callable[..., Coroutine],
        sync_interval: int = 30,
    ):
        self.load_clients = load_clients
        self.on_balance = on_balance
        self.on_orders = on_orders
        self.on_error = on_error
        self.sync_interval = sync_interval
        self.shutdown_event = asyncio.Event()

        # exchange_client_id → ExchangeClientConnection
        self._connections: dict[int, ExchangeClientConnection] = {}

    async def run(self) -> None:
        logger.info("ExchangeClientStreamManager запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        clients = await self.load_clients()
        await self._reconcile(clients)

        if not self._connections:
            logger.warning("Нет активных клиентов для WS-подписок.")

        sync_task = asyncio.create_task(self._sync_loop())

        await self.shutdown_event.wait()

        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task

        for conn in self._connections.values():
            await conn.close()

        logger.info("ExchangeClientStreamManager завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения, останавливаем стримы...")
        self.shutdown_event.set()

    async def _sync_loop(self) -> None:
        """Периодически загружает клиентов из БД и синхронизирует."""
        while not self.shutdown_event.is_set():
            await asyncio.sleep(self.sync_interval)
            clients = await self.load_clients()
            await self._reconcile(clients)

    async def _reconcile(
        self,
        clients: dict[int, AbstractExchangeClient],
    ) -> None:
        """Сравнивает текущие соединения с клиентами, обновляет."""
        new_client_ids = set(clients.keys())
        current_client_ids = set(self._connections.keys())

        for client_id in current_client_ids - new_client_ids:
            conn = self._connections.pop(client_id)
            logger.info(f"Закрываем соединение exchange_client_id={client_id}")
            await conn.close()

        for client_id in new_client_ids - current_client_ids:
            conn = ExchangeClientConnection(
                exchange_client=clients[client_id],
                exchange_client_id=client_id,
                on_balance=self.on_balance,
                on_orders=self.on_orders,
                on_error=self.on_error,
                shutdown_event=self.shutdown_event,
            )
            await conn.connect()
            await asyncio.sleep(0.5)
            self._connections[client_id] = conn
            logger.info(f"Открыто соединение exchange_client_id={client_id}")
