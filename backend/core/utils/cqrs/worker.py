"""BusWorker — RPCServer обёрнутый в BaseWorker lifecycle."""

from core.utils.cqrs.server import RPCServer
from core.utils.worker import BaseWorker


class BusWorker(BaseWorker):
    """RPCServer + BaseWorker lifecycle.

    Для случаев когда RPCServer — единственный компонент воркера.
    """

    def __init__(self, server: RPCServer, **kwargs) -> None:
        super().__init__(**kwargs)
        self._server = server

    async def _startup(self) -> None:
        await super()._startup()
        await self._server.start()

    async def _run(self) -> None:
        await self._server.run(self.shutdown_event)

    async def _shutdown(self) -> None:
        await self._server.stop(timeout=self.shutdown_timeout)
        await super()._shutdown()
