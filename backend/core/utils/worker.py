"""BaseWorker — базовый lifecycle для долгоживущих процессов."""

import asyncio
import signal
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from typing import Protocol, runtime_checkable

from loguru import logger

DEFAULT_SHUTDOWN_TIMEOUT = 30


@runtime_checkable
class Manager(Protocol):
    """Протокол для компонентов с lifecycle start/run/stop."""

    async def start(self) -> None: ...
    async def run(self, shutdown_event: asyncio.Event) -> None: ...
    async def stop(self) -> None: ...


class BaseWorker(ABC):
    """Базовый воркер: lifecycle + graceful shutdown.

    Подклассы реализуют _run() — основной цикл работы.
    """

    def __init__(
        self,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self.shutdown_timeout: float = shutdown_timeout
        self._on_startup: list[Awaitable[None]] = []
        self._on_shutdown: list[Awaitable[None]] = []
        self._shutdown_event: asyncio.Event = asyncio.Event()

    @property
    def shutdown_event(self) -> asyncio.Event:
        return self._shutdown_event

    def add_on_startup(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова перед запуском _run()."""
        self._on_startup.append(task)

    def add_on_shutdown(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова при остановке."""
        self._on_shutdown.append(task)

    async def launch(self) -> None:
        """Запускает воркер: signals → startup → run → shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        name = type(self).__name__
        logger.info(f"{name} запускается")
        try:
            await self._startup()
            logger.info(f"{name} запущен")
            await self._run()
        finally:
            logger.info(f"{name} останавливается")
            await self._shutdown()
            logger.info(f"{name} остановлен")

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
        for callback in self._on_shutdown:
            try:
                await asyncio.wait_for(
                    callback,
                    timeout=self.shutdown_timeout,
                )
            except TimeoutError:
                logger.warning(
                    f"{type(self).__name__} shutdown callback "
                    f"таймаут ({self.shutdown_timeout}с)"
                )
            except Exception as e:
                logger.error(f"{type(self).__name__} shutdown callback ошибка: {e}")
