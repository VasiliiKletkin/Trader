"""BalanceStreamWorker — BaseWorker обёртка для BalanceStreamManager."""

from core.utils.worker import BaseWorker
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.ws.loaders import load_balance_streams
from exchange_clients.domain.ws.manager import BalanceStreamManager


class BalanceStreamWorker(BaseWorker):
    """BalanceStreamManager + Pool lifecycle в одном воркере."""

    def __init__(self, pool: ExchangeClientPool, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pool = pool
        self._manager = BalanceStreamManager(
            pool=pool,
            load_streams=load_balance_streams,
        )
        self.add_background_task(pool.run(self.shutdown_event))
        self.add_on_shutdown(pool.close())

    async def _startup(self) -> None:
        await super()._startup()
        await self._manager.start()

    async def _run(self) -> None:
        await self._manager.run(self.shutdown_event)

    async def _shutdown(self) -> None:
        await self._manager.stop()
        await super()._shutdown()
