"""BusClient — отправляет сообщения в шину."""

from abc import ABC, abstractmethod

from core.utils.rpc.base import (
    BusConnectionError,
    BusHandlerError,
    BusTimeoutError,
    Message,
    Registry,
    Result,
)
from core.utils.rpc.broker import AbstractBusBroker
from core.utils.rpc.transport import TransportRequest, TransportResponse

DEFAULT_REPLY_TIMEOUT = 180


class AbstractBusClient(ABC):
    """Абстрактный клиент шины."""

    @abstractmethod
    async def execute(
        self,
        message: Message,
        timeout: int = DEFAULT_REPLY_TIMEOUT,
    ) -> Result | None:
        raise NotImplementedError


class BusClient(AbstractBusClient):
    """Отправляет сообщения через Redis Streams и ждёт ответ."""

    def __init__(self, broker: AbstractBusBroker) -> None:
        self._broker: AbstractBusBroker = broker

    async def execute(
        self,
        message: Message,
        timeout: int = DEFAULT_REPLY_TIMEOUT,
    ) -> Result | None:
        """Отправляет сообщение и ждёт ответ."""
        request: TransportRequest = TransportRequest.serialize(
            message=message,
            reply_timeout=timeout,
        )
        try:
            await self._broker.send(request=request)
        except ConnectionError as e:
            raise BusConnectionError(str(e)) from e
        try:
            response: TransportResponse = await self._broker.wait_reply(
                request_id=request.request_id,
                timeout=request.reply_timeout,
            )
        except TimeoutError as e:
            raise BusTimeoutError(
                f"Таймаут {timeout}с для {request.message_class_name}"
            ) from e
        except ConnectionError as e:
            raise BusConnectionError(str(e)) from e
        if not response.success:
            raise BusHandlerError(
                error_message=response.error_message or "Неизвестная ошибка",
                error_type=response.error_type,
                error_traceback=response.error_traceback,
            )
        return response.deserialize()


class LocalBusClient(AbstractBusClient):
    """Выполняет хэндлеры напрямую без Redis.

    Для каждого сообщения: instantiate() → async with → handler.handle().
    Используется когда exchange_client_worker не запущен.
    """

    async def execute(
        self,
        message: Message,
        timeout: int = DEFAULT_REPLY_TIMEOUT,
    ) -> Result | None:
        # Локальные импорты: циклическая зависимость
        # core.utils.rpc → client.py → exchange_clients → core.utils.rpc
        import exchange_clients.domain.rpc.handlers  # noqa: F401
        from exchange_clients.domain.rpc.messages import (
            ExchangeClientMessage,
        )
        from exchange_clients.models import ExchangeClient

        handler_cls = Registry.get_handler_class(type(message).__name__)
        if handler_cls is None:
            raise RuntimeError(f"Нет хендлера для {type(message).__name__}")

        if not isinstance(message, ExchangeClientMessage):
            raise TypeError(
                f"LocalBusClient поддерживает только "
                f"ExchangeClientMessage, получен "
                f"{type(message).__name__}"
            )

        ec = ExchangeClient.objects.select_related("exchange", "proxy").get(
            pk=message.exchange_client_id
        )
        client = ec.instantiate()

        async with client:
            handler = handler_cls(client=client)
            return await handler.handle(message=message)
