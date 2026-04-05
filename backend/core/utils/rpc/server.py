"""RPCServer — слушает и выполняет сообщения (без lifecycle)."""

import asyncio

from loguru import logger

from core.utils.rpc.base import (
    Handler,
    HandlerNotFoundError,
    Message,
    Registry,
    Result,
    UnknownMessageError,
)
from core.utils.rpc.broker import AbstractBusBroker
from core.utils.rpc.transport import TransportRequest, TransportResponse


class RPCServer:
    """Слушает стрим и выполняет сообщения конкурентно.

    Чистая логика без lifecycle — используется как компонент внутри BaseWorker.
    Подклассы переопределяют _resolve_handler() для DI.
    """

    def __init__(self, broker: AbstractBusBroker) -> None:
        self._broker: AbstractBusBroker = broker
        self._pending_tasks: set[asyncio.Task[None]] = set()

    def _resolve_handler(self, handler_cls: type, message: Message) -> Handler:
        """Создаёт экземпляр хендлера. Переопределяется в подклассах для DI."""
        return handler_cls()

    async def start(self) -> None:
        """Подписывается на стримы и создаёт consumer group."""
        handlers = Registry.get_registered_handlers()
        for message_class_name, handler_cls in handlers.items():
            group = f"{handler_cls.__module__}.{handler_cls.__qualname__}"
            self._broker.subscribe(
                stream=message_class_name,
                group=group,
            )
            logger.info(
                f"RPCServer хендлер {message_class_name} → {handler_cls.__name__}"
            )
        await self._broker.create_consumer_group()
        logger.info(f"RPCServer подключён ({len(handlers)} хендлеров)")

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Читает сообщения из broker и обрабатывает конкурентно."""
        while not shutdown_event.is_set():
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
            except ConnectionError as e:
                logger.error(f"RPCServer соединение потеряно: {e}")
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5)
                    break
                except TimeoutError:
                    pass
            except Exception as e:
                logger.error(f"RPCServer ошибка: {e}")

    async def stop(self) -> None:
        """Дожидается pending задач и закрывает broker."""
        for task in list(self._pending_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"RPCServer ошибка задачи: {e}")
        try:
            await self._broker.destroy_consumer()
        except Exception as e:
            logger.warning(f"RPCServer ошибка destroy_consumer: {e}")
        await self._broker.close()
        logger.info("RPCServer отключён")

    # --- Private ---

    async def _handle(self, message: Message) -> Result | None:
        handler_cls: type | None = Registry.get_handler_class(
            message_class_name=type(message).__name__,
        )
        if handler_cls is None:
            raise HandlerNotFoundError(f"Нет хендлера для {type(message).__name__}")
        handler: Handler = self._resolve_handler(
            handler_cls=handler_cls,
            message=message,
        )
        return await handler.handle(message=message)

    async def _process(
        self,
        message_id: str,
        stream: str,
        request: TransportRequest,
    ) -> None:
        try:
            message: Message | None = request.deserialize()
            if message is None:
                raise UnknownMessageError(
                    f"Неизвестное сообщение: {request.message_class_name}"
                )
            result: Result | None = await self._handle(message=message)
            response: TransportResponse = TransportResponse.serialize(
                request=request,
                result=result,
            )
        except Exception as e:
            logger.exception(
                f"RPCServer {request.message_class_name} [{request.request_id}]: {e}"
            )
            response = TransportResponse.serialize(
                request=request,
                exception=e,
            )
        try:
            await self._broker.reply(
                message_id=message_id,
                stream=stream,
                response=response,
                reply_ttl=int(request.timeout * 2),
            )
        except Exception as e:
            logger.error(f"RPCServer ошибка reply [{request.request_id}]: {e}")
