"""Redis-реализация брокера (Redis Streams + Lists)."""

import asyncio
import itertools
import uuid

import redis.asyncio as aio_redis
from loguru import logger
from pydantic import BaseModel

from core.utils.cqrs.broker import AbstractBusBroker
from core.utils.cqrs.transport import TransportRequest, TransportResponse


class RedisStreamSubscription(BaseModel, frozen=True):
    """Подписка: стрим + consumer group."""

    stream: str
    group: str


class RedisBusBroker(AbstractBusBroker):
    """Redis-реализация брокера.

    Каждый тип сообщения = отдельный Redis Stream.
    Каждый хендлер = отдельная consumer group.
    Consumer name = UUID (уникальный для процесса).
    Reply key = request_id.
    """

    def __init__(
        self,
        redis: aio_redis.Redis,
    ) -> None:
        self._redis: aio_redis.Redis = redis
        self._consumer_name: str = uuid.uuid4().hex
        self._subscriptions: dict[str, RedisStreamSubscription] = {}
        self._subscription_cycle: itertools.cycle[RedisStreamSubscription] = (
            itertools.cycle(())
        )

    # --- Subscriptions ---

    def subscribe(self, stream: str, group: str) -> None:
        if stream not in self._subscriptions:
            self._subscriptions[stream] = RedisStreamSubscription(
                stream=stream,
                group=group,
            )

    # --- Consumer operations ---

    async def create_consumer_group(self) -> None:
        for sub in self._subscriptions.values():
            try:
                await self._redis.xgroup_create(
                    name=sub.stream,
                    groupname=sub.group,
                    id="0",
                    mkstream=True,
                )
            except aio_redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
        self._subscription_cycle = itertools.cycle(
            self._subscriptions.values(),
        )

    async def read(
        self,
        timeout: int = 1,
    ) -> tuple[str, str, TransportRequest] | None:
        if not self._subscriptions:
            return None

        # Неблокирующий опрос подписок с ротацией.
        # Каждый вызов продолжает с того места, где остановился.
        for sub in itertools.islice(self._subscription_cycle, len(self._subscriptions)):
            try:
                result = await self._try_read_stream(sub=sub)
                if result is not None:
                    return result
            except aio_redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    logger.warning(
                        f"RedisBusBroker: группа удалена для {sub.stream}, "
                        f"пересоздаю..."
                    )
                    await self.create_consumer_group()
                else:
                    raise

        await asyncio.sleep(timeout)
        return None

    async def reply(
        self,
        message_id: str,
        stream: str,
        response: TransportResponse,
        reply_ttl: int,
    ) -> None:
        sub: RedisStreamSubscription | None = self._subscriptions.get(stream)
        pipe = self._redis.pipeline()
        pipe.rpush(response.request_id, response.model_dump_json())
        pipe.expire(response.request_id, reply_ttl)
        if sub:
            pipe.xack(sub.stream, sub.group, message_id)
            pipe.xdel(sub.stream, message_id)
        await pipe.execute()

    # --- Producer operations ---

    async def send(self, request: TransportRequest) -> None:
        await self._redis.xadd(
            name=request.message_class_name,
            fields={"data": request.model_dump_json()},
        )

    async def wait_reply(
        self,
        request_id: str,
        timeout: float = 30.0,
    ) -> TransportResponse:
        raw_result = await self._redis.blpop(
            keys=request_id,
            timeout=timeout,
        )
        if raw_result is None:
            raise TimeoutError(f"Таймаут ожидания ответа для request_id={request_id}")
        _, raw = raw_result
        return TransportResponse.model_validate_json(json_data=raw)

    # --- Lifecycle ---

    async def destroy_consumer(self) -> None:
        """Удаляет consumer из всех групп."""
        for sub in self._subscriptions.values():
            try:
                await self._redis.xgroup_delconsumer(
                    name=sub.stream,
                    groupname=sub.group,
                    consumername=self._consumer_name,
                )
            except Exception as e:
                logger.warning(
                    f"Ошибка удаления consumer {self._consumer_name}"
                    f" из {sub.stream}/{sub.group}: {e}"
                )

    async def close(self) -> None:
        await self._redis.close()

    # --- Private ---

    async def _try_read_stream(
        self,
        sub: RedisStreamSubscription,
    ) -> tuple[str, str, TransportRequest] | None:
        """Неблокирующее чтение одного сообщения из стрима."""
        results = await self._redis.xreadgroup(
            groupname=sub.group,
            consumername=self._consumer_name,
            streams={sub.stream: ">"},
            count=1,
        )
        if not results:
            return None

        _, messages = results[0]
        if not messages:
            return None

        message_id, fields = messages[0]
        raw = fields.get("data")
        if not raw:
            logger.warning(
                f"RedisBusBroker: пустое сообщение {message_id} "
                f"в стриме {sub.stream}, пропускаю"
            )
            await self._ack_and_delete(
                stream=sub.stream,
                group=sub.group,
                message_id=message_id,
            )
            return None

        try:
            request: TransportRequest = TransportRequest.model_validate_json(
                json_data=raw,
            )
        except Exception as e:
            logger.error(
                f"RedisBusBroker: невалидное сообщение {message_id} "
                f"в стриме {sub.stream}: {e}"
            )
            await self._ack_and_delete(
                stream=sub.stream,
                group=sub.group,
                message_id=message_id,
            )
            return None

        return (message_id, sub.stream, request)

    async def _ack_and_delete(
        self,
        stream: str,
        group: str,
        message_id: str,
    ) -> None:
        """Подтверждает и удаляет пустое сообщение."""
        pipe = self._redis.pipeline()
        pipe.xack(stream, group, message_id)
        pipe.xdel(stream, message_id)
        await pipe.execute()
