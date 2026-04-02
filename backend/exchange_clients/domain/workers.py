"""BaseWorker обёртки для exchange client компонентов."""

import asyncio

from core.bus import create_redis_bus_broker
from core.utils.worker import BaseWorker
from exchange_clients.domain.messages.handlers import *  # noqa: F403
from exchange_clients.domain.messages.server import ExchangeClientRPCServer
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.manager import (
    BalanceStreamManager,
    CandleStreamManager,
    CandleSubscriptionsLoader,
    OrderStreamManager,
    StreamsLoader,
)


class CandleStreamWorker(BaseWorker):
    """CandleStreamManager + Pool lifecycle."""

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_subscriptions: CandleSubscriptionsLoader,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.pool = pool
        self.candle_manager = CandleStreamManager(
            pool=pool,
            load_subscriptions=load_subscriptions,
        )
        self.add_on_startup(pool.start())
        self.add_on_startup(self.candle_manager.start())
        self.add_on_shutdown(self.candle_manager.stop())
        self.add_on_shutdown(pool.stop())

    async def _run(self) -> None:
        await asyncio.gather(
            self.pool.run(self.shutdown_event),
            self.candle_manager.run(self.shutdown_event),
        )


class BalanceStreamWorker(BaseWorker):
    """BalanceStreamManager + Pool lifecycle."""

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_streams: StreamsLoader,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.pool = pool
        self.balance_manager = BalanceStreamManager(
            pool=pool,
            load_streams=load_streams,
        )
        self.add_on_startup(pool.start())
        self.add_on_startup(self.balance_manager.start())
        self.add_on_shutdown(self.balance_manager.stop())
        self.add_on_shutdown(pool.stop())

    async def _run(self) -> None:
        await asyncio.gather(
            self.pool.run(self.shutdown_event),
            self.balance_manager.run(self.shutdown_event),
        )


class ExchangeClientWorker(BaseWorker):
    """REST + WS балансы/ордера + Pool lifecycle."""

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_balance_streams: StreamsLoader,
        load_order_streams: StreamsLoader,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.pool = pool
        self.rpc_server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        self.balance_manager = BalanceStreamManager(
            pool=pool,
            load_streams=load_balance_streams,
        )
        self.order_manager = OrderStreamManager(
            pool=pool,
            load_streams=load_order_streams,
        )
        self.add_on_startup(pool.start())
        self.add_on_startup(self.rpc_server.start())
        self.add_on_startup(self.balance_manager.start())
        self.add_on_startup(self.order_manager.start())
        self.add_on_shutdown(self.rpc_server.stop())
        self.add_on_shutdown(self.balance_manager.stop())
        self.add_on_shutdown(self.order_manager.stop())
        self.add_on_shutdown(pool.stop())

    async def _run(self) -> None:
        await asyncio.gather(
            self.pool.run(self.shutdown_event),
            self.rpc_server.run(self.shutdown_event),
            self.balance_manager.run(self.shutdown_event),
            self.order_manager.run(self.shutdown_event),
        )


class ExchangeClientBusWorker(BaseWorker):
    """RPCServer + Pool lifecycle."""

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        super().__init__(**kwargs)
        self.pool = pool
        self.server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        self.add_on_startup(pool.start())
        self.add_on_startup(self.server.start())
        self.add_on_shutdown(self.server.stop())
        self.add_on_shutdown(pool.stop())

    async def _run(self) -> None:
        await asyncio.gather(
            self.pool.run(self.shutdown_event),
            self.server.run(self.shutdown_event),
        )


class UnifiedExchangeClientWorker(BaseWorker):
    """REST + WS OHLCV + WS Balance/Orders.

    Все компоненты равноправны, используют общий ExchangeClientPool.
    """

    def __init__(
        self,
        pool: ExchangeClientPool,
        load_candle_subscriptions: CandleSubscriptionsLoader,
        load_balance_streams: StreamsLoader,
        load_order_streams: StreamsLoader,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.pool = pool
        self.rpc_server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        self.candle_manager = CandleStreamManager(
            pool=pool,
            load_subscriptions=load_candle_subscriptions,
        )
        self.balance_manager = BalanceStreamManager(
            pool=pool,
            load_streams=load_balance_streams,
        )
        self.order_manager = OrderStreamManager(
            pool=pool,
            load_streams=load_order_streams,
        )
        self.add_on_startup(pool.start())
        self.add_on_startup(self.rpc_server.start())
        self.add_on_startup(self.candle_manager.start())
        self.add_on_startup(self.balance_manager.start())
        self.add_on_startup(self.order_manager.start())
        self.add_on_shutdown(self.rpc_server.stop())
        self.add_on_shutdown(self.candle_manager.stop())
        self.add_on_shutdown(self.balance_manager.stop())
        self.add_on_shutdown(self.order_manager.stop())
        self.add_on_shutdown(pool.stop())

    async def _run(self) -> None:
        await asyncio.gather(
            self.pool.run(self.shutdown_event),
            self.rpc_server.run(self.shutdown_event),
            self.candle_manager.run(self.shutdown_event),
            self.balance_manager.run(self.shutdown_event),
            self.order_manager.run(self.shutdown_event),
        )
