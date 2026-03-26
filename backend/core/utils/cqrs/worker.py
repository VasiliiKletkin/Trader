"""BusWorker — слушает и выполняет сообщения."""

import asyncio
import signal
from collections.abc import Awaitable

from loguru import logger

from core.utils.cqrs.base import Handler, Message, Registry, Result
from core.utils.cqrs.broker import BusBroker
from core.utils.cqrs.transport import TransportRequest, TransportResponse

SHUTDOWN_TIMEOUT = 30


class BusWorker:
    """Слушает и выполняет сообщения.

    Резолвит хендлер из реестра и вызывает handle().
    Подклассы переопределяют _get_handler() для кастомной логики.
    """

    def __init__(self, broker: BusBroker) -> None:
        self._broker: BusBroker = broker
        # Корутины, запускаемые параллельно с _listen_loop (например pool.sync_loop)
        self._background_tasks: list[Awaitable[None]] = []
        # Корутины, вызываемые при shutdown (например pool.close)
        self._on_shutdown: list[Awaitable[None]] = []
        # Флаг для graceful shutdown (SIGTERM/SIGINT)
        self._shutdown_event: asyncio.Event = asyncio.Event()
        # Задачи _process, выполняющиеся конкурентно в данный момент
        self._pending_tasks: set[asyncio.Task[None]] = set()

    @property
    def shutdown_event(self) -> asyncio.Event:
        return self._shutdown_event

    def add_background_task(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для запуска параллельно с listen loop."""
        self._background_tasks.append(task)

    def add_on_shutdown(self, task: Awaitable[None]) -> None:
        """Добавляет корутину для вызова при остановке worker'а."""
        self._on_shutdown.append(task)

    async def launch(self) -> None:
        """Запускает worker."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        self._subscribe()
        await self._broker.create_consumer_group()
        logger.info("BusWorker: запущен")

        try:
            await asyncio.gather(
                self._listen_loop(),
                *self._background_tasks,
            )
        finally:
            await self._shutdown()

    def _create_handler(self, handler_cls: type, message: Message) -> Handler:
        """Создаёт экземпляр хендлера. Переопределяется в подклассах для DI."""
        return handler_cls()

    async def _handle(self, message: Message) -> Result | None:
        """Резолвит хендлер из реестра и выполняет сообщение."""
        handler_cls: type | None = Registry.get_handler_class(
            message_class_name=type(message).__name__,
        )
        if handler_cls is None:
            raise RuntimeError(f"Нет хендлера для {type(message).__name__}")
        handler: Handler = self._create_handler(
            handler_cls=handler_cls,
            message=message,
        )
        return await handler.handle(message=message)

    # --- Private ---

    def _subscribe(self) -> None:
        """Подписывает broker на стримы всех зарегистрированных хендлеров."""
        for (
            message_class_name,
            handler_cls,
        ) in Registry.get_registered_handlers().items():
            group: str = f"{handler_cls.__module__}.{handler_cls.__qualname__}"
            self._broker.subscribe(
                stream=message_class_name,
                group=group,
            )
            logger.debug(f"BusWorker: {message_class_name} → {group}")

    async def _shutdown(self) -> None:
        """Ожидает pending задачи, вызывает on_shutdown, закрывает broker."""
        logger.info("BusWorker: завершение...")
        if self._pending_tasks:
            logger.info(
                "BusWorker: ожидание {} задач...",
                len(self._pending_tasks),
            )
            _, pending = await asyncio.wait(
                self._pending_tasks,
                timeout=SHUTDOWN_TIMEOUT,
            )
            if pending:
                logger.warning(
                    "BusWorker: {} задач не завершились за 30с, отменяю...",
                    len(pending),
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        for callback in self._on_shutdown:
            await callback
        await self._broker.close()
        logger.info("BusWorker: завершён.")

    async def _listen_loop(self) -> None:
        """Читает сообщения из broker и запускает _process для каждого."""
        while not self._shutdown_event.is_set():
            try:
                transport_result = await self._broker.read(timeout=1)
                if transport_result is None:
                    continue

                message_id, stream, request = transport_result
                task: asyncio.Task[None] = asyncio.create_task(
                    self._process(
                        message_id=message_id,
                        stream=stream,
                        request=request,
                    ),
                )
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"BusWorker: {e}")

    async def _process(
        self,
        message_id: str,
        stream: str,
        request: TransportRequest,
    ) -> None:
        """Десериализует, выполняет handler и отправляет ответ в broker."""
        message: Message | None = request.deserialize()
        try:
            if message is None:
                raise RuntimeError(
                    f"Неизвестное сообщение: {request.message_class_name}"
                )
            result: Result | None = await self._handle(message=message)
            response: TransportResponse = TransportResponse.serialize(
                request=request,
                result=result,
            )
        except Exception as e:
            logger.exception(f"Ошибка {request.message_class_name}: {e}")
            response = TransportResponse.serialize(
                request=request,
                exception=e,
            )
        await self._broker.reply(
            message_id=message_id,
            stream=stream,
            response=response,
            reply_ttl=int(request.timeout * 2),
        )
