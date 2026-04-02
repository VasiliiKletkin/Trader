"""BaseWorker обёртки для exchange client компонентов."""

import asyncio

from core.bus import create_redis_bus_broker
from core.utils.cqrs import BusWorker
from core.utils.worker import BaseWorker
from exchange_clients.domain.messages.handlers import *  # noqa: F403
from exchange_clients.domain.messages.server import ExchangeClientRPCServer
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.loaders import load_balance_streams, load_order_streams
from exchange_clients.domain.ws.manager import BalanceStreamManager, CandleStreamManager


class CandleStreamWorker(BaseWorker):
    """CandleStreamManager + Pool lifecycle."""

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._manager = CandleStreamManager(pool=pool)
        self.add_background_task(pool.run(self.shutdown_event))
        self.add_on_startup(self._manager.start())
        self.add_on_shutdown(self._manager.stop())
        self.add_on_shutdown(pool.close())

    async def _run(self) -> None:
        await self._manager.run(self.shutdown_event)


class BalanceStreamWorker(BaseWorker):
    """BalanceStreamManager + Pool lifecycle."""

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._manager = BalanceStreamManager(
            pool=pool,
            load_streams=load_balance_streams,
        )
        self.add_background_task(pool.run(self.shutdown_event))
        self.add_on_startup(self._manager.start())
        self.add_on_shutdown(self._manager.stop())
        self.add_on_shutdown(pool.close())

    async def _run(self) -> None:
        await self._manager.run(self.shutdown_event)


class OrderStreamWorker(BaseWorker):
    """OrderStreamManager + Pool lifecycle."""

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._manager = BalanceStreamManager(
            pool=pool,
            load_streams=load_order_streams,
        )
        self.add_background_task(pool.run(self.shutdown_event))
        self.add_on_startup(self._manager.start())
        self.add_on_shutdown(self._manager.stop())
        self.add_on_shutdown(pool.close())

    async def _run(self) -> None:
        await self._manager.run(self.shutdown_event)


class ExchangeClientBusWorker(BusWorker):
    """RPCServer + Pool lifecycle."""

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        super().__init__(server=server, **kwargs)
        self.add_background_task(task=pool.run(self.shutdown_event))
        self.add_on_shutdown(task=pool.close())


class UnifiedExchangeClientWorker(BaseWorker):
    """REST + WS OHLCV + WS Balance/Orders.

    Все компоненты равноправны, используют общий ExchangeClientPool.
    """

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pool = pool
        self._rpc_server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        self._candle_stream = CandleStreamManager(pool=pool)
        self._balance_stream = BalanceStreamManager(
            pool=pool,
            load_streams=load_balance_streams,
        )
        self._order_stream = BalanceStreamManager(
            pool=pool,
            load_streams=load_order_streams,
        )
        self.add_on_startup(self._rpc_server.start())
        self.add_on_startup(self._candle_stream.start())
        self.add_on_startup(self._balance_stream.start())
        self.add_on_startup(self._order_stream.start())
        self.add_on_shutdown(self._rpc_server.stop())
        self.add_on_shutdown(self._candle_stream.stop())
        self.add_on_shutdown(self._balance_stream.stop())
        self.add_on_shutdown(self._order_stream.stop())
        self.add_on_shutdown(pool.close())

    async def _run(self) -> None:
        await asyncio.gather(
            self._pool.run(self.shutdown_event),
            self._rpc_server.run(self.shutdown_event),
            self._candle_stream.run(self.shutdown_event),
            self._balance_stream.run(self.shutdown_event),
            self._order_stream.run(self.shutdown_event),
        )
