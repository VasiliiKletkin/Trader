"""Unified exchange client worker: REST + WS в одном процессе."""

import asyncio

from core.bus import create_redis_bus_broker
from core.utils.worker import BaseWorker
from exchange_clients.domain.messages.handlers import *  # noqa: F403
from exchange_clients.domain.messages.server import ExchangeClientRPCServer
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.candle_stream import CandleStreamManager
from exchange_clients.domain.ws.loaders import load_balance_streams, load_order_streams
from exchange_clients.domain.ws.manager import BalanceStreamManager


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

    async def _startup(self) -> None:
        await super()._startup()
        await self._rpc_server.start()
        await self._candle_stream.start()
        await self._balance_stream.start()
        await self._order_stream.start()

    async def _run(self) -> None:
        await asyncio.gather(
            self._pool.run(self.shutdown_event),
            self._rpc_server.run(self.shutdown_event),
            self._candle_stream.run(self.shutdown_event),
            self._balance_stream.run(self.shutdown_event),
            self._order_stream.run(self.shutdown_event),
        )

    async def _shutdown(self) -> None:
        await self._rpc_server.stop(timeout=self.shutdown_timeout)
        await self._candle_stream.stop()
        await self._balance_stream.stop()
        await self._order_stream.stop()
        await self._pool.close()
        await super()._shutdown()
