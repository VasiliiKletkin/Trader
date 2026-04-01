"""BaseWorker — базовый lifecycle для долгоживущих процессов."""

import asyncio
import signal
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from enum import StrEnum

from loguru import logger


class WorkerState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


DEFAULT_SHUTDOWN_TIMEOUT = 30


class BaseWorker(ABC):
    """Базовый воркер: lifecycle + background tasks + graceful shutdown.

    Подклассы реализуют _run() — основной цикл работы.
    Опционально переопределяют _startup() и _shutdown() для хуков.
    """

    def __init__(
        self,
        name: str | None = None,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self.name: str = name or type(self).__name__
        self.shutdown_timeout: float = shutdown_timeout
        self._state: WorkerState = WorkerState.CREATED
        self._background_tasks: list[Awaitable[None]] = []
        self._on_startup: list[Awaitable[None]] = []
        self._on_shutdown: list[Awaitable[None]] = []
        self._shutdown_event: asyncio.Event = asyncio.Event()

    @property
    def state(self) -> WorkerState:
        return self._state

    @property
    def shutdown_event(self) -> asyncio.Event:
        return self._shutdown_event

    def add_background_task(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для запуска параллельно с _run()."""
        self._background_tasks.append(task)

    def add_on_startup(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова перед запуском _run()."""
        self._on_startup.append(task)

    def add_on_shutdown(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова при остановке."""
        self._on_shutdown.append(task)

    async def launch(self) -> None:
        """Запускает воркер: signals → startup → run + background → shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        self._state = WorkerState.STARTING
        bg = len(self._background_tasks)
        logger.info(f"{self.name} запускается (background tasks: {bg})")
        try:
            await self._startup()
            self._state = WorkerState.RUNNING
            logger.info(f"{self.name} запущен")
            await asyncio.gather(
                self._run(),
                *self._background_tasks,
            )
        finally:
            self._state = WorkerState.STOPPING
            await self._shutdown()
            self._state = WorkerState.STOPPED

    @abstractmethod
    async def _run(self) -> None:
        """Основной цикл работы. Реализуется в подклассах."""
        ...

    async def _startup(self) -> None:
        """Хуки перед запуском _run()."""
        for callback in self._on_startup:
            await callback

    async def _shutdown(self) -> None:
        """Graceful shutdown: вызывает on_shutdown callbacks с таймаутом."""
        logger.info(f"{self.name} останавливается")
        for callback in self._on_shutdown:
            try:
                await asyncio.wait_for(
                    callback,
                    timeout=self.shutdown_timeout,
                )
            except TimeoutError:
                logger.warning(
                    f"{self.name} shutdown callback таймаут ({self.shutdown_timeout}с)"
                )
            except Exception as e:
                logger.error(f"{self.name} shutdown callback ошибка: {e}")
        logger.info(f"{self.name} остановлен")
