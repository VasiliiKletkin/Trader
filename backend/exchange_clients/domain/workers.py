"""BaseWorker обёртки для exchange client компонентов."""

from core.utils.worker import BaseWorker
from exchange_clients.domain.managers import (
    ExchangeClientPool,
    StreamManager,
)
from exchange_clients.domain.rpc.handlers import *  # noqa: F403
from exchange_clients.domain.rpc.server import ExchangeClientRPCServer


class RPCWorker(BaseWorker):
    """Pool + RPC."""

    def __init__(
        self,
        pool: ExchangeClientPool,
        rpc_server: ExchangeClientRPCServer,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.add_on_startup(pool.start())
        self.add_on_startup(rpc_server.start())
        self.add_task(pool.run(self.shutdown_event))
        self.add_task(rpc_server.run(self.shutdown_event))
        self.add_on_shutdown(rpc_server.stop())
        self.add_on_shutdown(pool.stop())


class ExchangeClientStreamWorker(BaseWorker):
    """Pool + WS балансы/ордера."""

    def __init__(
        self,
        pool: ExchangeClientPool,
        stream_manager: StreamManager,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.add_on_startup(pool.start())
        self.add_on_startup(stream_manager.start())
        self.add_task(pool.run(self.shutdown_event))
        self.add_task(stream_manager.run(self.shutdown_event))
        self.add_on_shutdown(stream_manager.stop())
        self.add_on_shutdown(pool.stop())


class CandleStreamWorker(BaseWorker):
    """Pool + WS свечи."""

    def __init__(
        self,
        pool: ExchangeClientPool,
        stream_manager: StreamManager,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.add_on_startup(pool.start())
        self.add_on_startup(stream_manager.start())
        self.add_task(pool.run(self.shutdown_event))
        self.add_task(stream_manager.run(self.shutdown_event))
        self.add_on_shutdown(stream_manager.stop())
        self.add_on_shutdown(pool.stop())
