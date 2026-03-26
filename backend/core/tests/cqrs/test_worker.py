"""Тесты BusWorker."""

import pytest

from core.utils.cqrs.base import Handler, Message
from core.utils.cqrs.worker import BusWorker

from .conftest import FailMessage, PingMessage, PingResult


class FakeBroker:
    """Минимальный брокер для unit-тестов."""

    async def close(self):
        pass


@pytest.fixture()
def worker() -> BusWorker:
    return BusWorker(broker=FakeBroker())  # type: ignore[arg-type]


class TestWorkerHandle:
    """Тесты _handle — резолвит handler и выполняет."""

    @pytest.mark.asyncio()
    async def test_handle_success(self, worker: BusWorker):
        message = PingMessage(value="test")
        result = await worker._handle(message=message)
        assert isinstance(result, PingResult)
        assert result.pong == "test"

    @pytest.mark.asyncio()
    async def test_handle_error(self, worker: BusWorker):
        message = FailMessage()
        with pytest.raises(ValueError, match="test error"):
            await worker._handle(message=message)

    @pytest.mark.asyncio()
    async def test_handle_unknown_message(self, worker: BusWorker):
        class UnregisteredMessage(Message):
            pass

        with pytest.raises(RuntimeError, match="Нет хендлера"):
            await worker._handle(message=UnregisteredMessage())


class TestWorkerCreateHandler:
    """Тесты _create_handler — точка расширения для DI."""

    def test_create_handler_default(self, worker: BusWorker):
        from .conftest import PingHandler

        handler: Handler = worker._create_handler(
            handler_cls=PingHandler,
            message=PingMessage(value="x"),
        )
        assert isinstance(handler, PingHandler)

    def test_create_handler_override(self):
        """Подкласс может переопределить _create_handler для DI."""

        class CustomWorker(BusWorker):
            def _create_handler(
                self,
                handler_cls: type,
                message: Message,
            ) -> Handler:
                return handler_cls()  # type: ignore[call-arg]

        worker = CustomWorker(broker=FakeBroker())  # type: ignore[arg-type]
        message = PingMessage(value="di")
        handler = worker._create_handler(
            handler_cls=type(None),  # не важно для теста
            message=message,
        )
        assert handler is None
