"""BusWorker для exchange client."""

from core.utils.cqrs import BusWorker
from exchange_clients.domain.messages.server import ExchangeClientRPCServer
from exchange_clients.domain.pool import ExchangeClientPool

from .handlers import *  # noqa: F403


class ExchangeClientBusWorker(BusWorker):
    """RPCServer + Pool lifecycle в одном воркере."""

    def __init__(self, pool: ExchangeClientPool) -> None:
        from core.bus import create_redis_bus_broker

        server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        super().__init__(server=server)
        self.add_background_task(task=pool.run(self.shutdown_event))
        self.add_on_shutdown(task=pool.close())
