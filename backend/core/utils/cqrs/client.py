"""BusClient — отправляет команды/запросы в шину."""

from typing import Any

import redis.asyncio as aio_redis
from django.conf import settings

from core.utils.cqrs.broker import BusBroker
from core.utils.cqrs.commands import BaseMessage
from core.utils.cqrs.redis.broker import RedisBusBroker
from core.utils.cqrs.transport import TransportRequest


class BusClient:
    """Отправляет команды/запросы в шину и ждёт ответ."""

    def __init__(self, broker: BusBroker) -> None:
        self._broker = broker

    async def execute(
        self,
        message: BaseMessage[Any],
        timeout: float = 30.0,
    ) -> Any:
        """Отправляет команду/запрос и ждёт ответ."""
        request = TransportRequest.from_message(message)
        await self._broker.send(request)

        response = await self._broker.wait_reply(request.request_id, timeout=timeout)
        if not response.success:
            raise RuntimeError(response.error)
        return response.parse_result(message._result_adapter)


_client: BusClient | None = None


def get_bus_client() -> BusClient:
    """Возвращает синглтон BusClient."""
    global _client
    if _client is None:
        rs = settings.REDIS
        broker = RedisBusBroker(
            redis=aio_redis.Redis(
                host=str(rs["HOST"]),
                port=int(rs["PORT"]),
                db=int(rs["BUS_DATABASE"]),
                password=str(rs["PASSWORD"]) or None,
                decode_responses=True,
            ),
        )
        _client = BusClient(broker=broker)
    return _client
