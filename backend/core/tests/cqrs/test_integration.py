"""Интеграционные тесты: Client → Worker → Response."""

import asyncio

import pytest

from core.utils.cqrs.base import BusError
from core.utils.cqrs.broker import BusBroker
from core.utils.cqrs.client import BusClient
from core.utils.cqrs.transport import TransportRequest, TransportResponse
from core.utils.cqrs.worker import BusWorker

from .conftest import FailMessage, NoResultMessage, PingMessage, PingResult


class InMemoryBroker(BusBroker):
    """In-memory брокер для тестов.

    send() кладёт в очередь, read() достаёт.
    reply() кладёт ответ, wait_reply() достаёт.
    """

    def __init__(self) -> None:
        self._messages: asyncio.Queue[tuple[str, TransportRequest]] = asyncio.Queue()
        self._replies: dict[str, asyncio.Future[TransportResponse]] = {}
        self._subscriptions: dict[str, str] = {}

    def subscribe(self, stream: str, group: str) -> None:
        self._subscriptions[stream] = group

    async def create_consumer_group(self) -> None:
        pass

    async def read(
        self,
        timeout: int = 1,
    ) -> tuple[str, str, TransportRequest] | None:
        try:
            msg_id, request = await asyncio.wait_for(
                self._messages.get(),
                timeout=timeout,
            )
            return (msg_id, request.message_class_name, request)
        except TimeoutError:
            return None

    async def reply(
        self,
        message_id: str,
        stream: str,
        response: TransportResponse,
        reply_ttl: int,
    ) -> None:
        future = self._replies.get(response.request_id)
        if future and not future.done():
            future.set_result(response)

    async def send(self, request: TransportRequest) -> None:
        self._replies[request.request_id] = asyncio.get_event_loop().create_future()
        await self._messages.put(("msg-1", request))

    async def wait_reply(
        self,
        request_id: str,
        timeout: float = 30.0,
    ) -> TransportResponse:
        future = self._replies[request_id]
        return await asyncio.wait_for(future, timeout=timeout)

    async def close(self) -> None:
        pass


@pytest.fixture()
def broker() -> InMemoryBroker:
    return InMemoryBroker()


@pytest.fixture()
def client(broker: InMemoryBroker) -> BusClient:
    return BusClient(broker=broker)


@pytest.fixture()
def worker(broker: InMemoryBroker) -> BusWorker:
    return BusWorker(broker=broker)


class TestIntegration:
    """Полный round-trip через in-memory broker."""

    @pytest.mark.asyncio()
    async def test_execute_success(
        self,
        client: BusClient,
        worker: BusWorker,
    ):
        """Client.execute → Worker._process → PingResult."""

        async def run_worker_once():
            transport_result = await worker._broker.read(timeout=5)
            assert transport_result is not None
            message_id, stream, request = transport_result
            await worker._process(
                message_id=message_id,
                stream=stream,
                request=request,
            )

        result, _ = await asyncio.gather(
            client.execute(
                message=PingMessage(value="integration"),
                timeout=5.0,
            ),
            run_worker_once(),
        )

        assert isinstance(result, PingResult)
        assert result.pong == "integration"

    @pytest.mark.asyncio()
    async def test_execute_handler_error(
        self,
        client: BusClient,
        worker: BusWorker,
    ):
        """Handler бросает ошибку → BusError на клиенте."""

        async def run_worker_once():
            transport_result = await worker._broker.read(timeout=5)
            assert transport_result is not None
            message_id, stream, request = transport_result
            await worker._process(
                message_id=message_id,
                stream=stream,
                request=request,
            )

        with pytest.raises(BusError, match="test error"):
            await asyncio.gather(
                client.execute(
                    message=FailMessage(),
                    timeout=5.0,
                ),
                run_worker_once(),
            )

    @pytest.mark.asyncio()
    async def test_execute_none_result(
        self,
        client: BusClient,
        worker: BusWorker,
    ):
        """Handler возвращает None → клиент получает None."""

        async def run_worker_once():
            transport_result = await worker._broker.read(timeout=5)
            assert transport_result is not None
            message_id, stream, request = transport_result
            await worker._process(
                message_id=message_id,
                stream=stream,
                request=request,
            )

        result, _ = await asyncio.gather(
            client.execute(
                message=NoResultMessage(),
                timeout=5.0,
            ),
            run_worker_once(),
        )

        assert result is None
