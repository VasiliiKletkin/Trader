"""BusClient — отправляет сообщения в шину."""

from core.utils.cqrs.base import BusError, Message, Result
from core.utils.cqrs.broker import BusBroker
from core.utils.cqrs.transport import TransportRequest, TransportResponse


class BusClient:
    """Отправляет сообщения в шину и ждёт ответ."""

    def __init__(self, broker: BusBroker) -> None:
        self._broker: BusBroker = broker

    async def execute(
        self,
        message: Message,
        timeout: float = 30.0,
    ) -> Result | None:
        """Отправляет сообщение и ждёт ответ."""
        request: TransportRequest = TransportRequest.serialize(
            message=message,
            timeout=timeout,
        )
        await self._broker.send(request=request)
        response: TransportResponse = await self._broker.wait_reply(
            request_id=request.request_id,
            timeout=timeout,
        )
        if not response.success:
            raise BusError(
                message=response.error or "Неизвестная ошибка",
                error_type=response.error_type,
            )
        return response.deserialize()
