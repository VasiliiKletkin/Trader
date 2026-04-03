"""BaseWorker — базовый lifecycle для долгоживущих процессов."""

import asyncio
import signal
from collections.abc import Awaitable, Coroutine

from loguru import logger

DEFAULT_SHUTDOWN_TIMEOUT = 30


class BaseWorker:
    """Базовый воркер: lifecycle + graceful shutdown.

    Компоненты добавляются через add_task / add_on_startup / add_on_shutdown.
    """

    def __init__(
        self,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_event = asyncio.Event()
        self._tasks: list[Coroutine] = []
        self._on_startup: list[Awaitable[None]] = []
        self._on_shutdown: list[Awaitable[None]] = []

    def add_task(self, task: Coroutine) -> None:
        """Добавляет корутину для запуска в основном цикле."""
        self._tasks.append(task)

    def add_on_startup(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова перед запуском."""
        self._on_startup.append(task)

    def add_on_shutdown(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова при остановке."""
        self._on_shutdown.append(task)

    async def launch(self) -> None:
        """signals → startup → gather(tasks) → shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.shutdown_event.set)

        logger.info("Воркер запускается")
        try:
            await self._startup()
            logger.info("Воркер запущен")
            await asyncio.gather(*self._tasks)
        finally:
            logger.info("Воркер останавливается")
            await self._shutdown()
            logger.info("Воркер остановлен")

    async def _startup(self) -> None:
        """Хуки перед запуском."""
        for callback in self._on_startup:
            await callback

    async def _shutdown(self) -> None:
        """Graceful shutdown с таймаутом на каждый callback."""
        for callback in self._on_shutdown:
            try:
                await asyncio.wait_for(
                    callback,
                    timeout=self.shutdown_timeout,
                )
            except TimeoutError:
                logger.warning(f"Shutdown таймаут ({self.shutdown_timeout}с)")
            except Exception as e:
                logger.error(f"Shutdown ошибка: {e}")
