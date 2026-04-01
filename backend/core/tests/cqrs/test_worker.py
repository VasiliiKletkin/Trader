"""Тесты RPCServer."""

import pytest

from core.utils.cqrs.base import Handler, Message
from core.utils.cqrs.server import RPCServer

from .conftest import FailMessage, PingMessage, PingResult


class FakeBroker:
    """Минимальный брокер для unit-тестов."""

    async def close(self):
        pass


@pytest.fixture()
def server() -> RPCServer:
    return RPCServer(broker=FakeBroker())  # type: ignore[arg-type]


class TestServerHandle:
    """Тесты _handle — резолвит handler и выполняет."""

    @pytest.mark.asyncio()
    async def test_handle_success(self, server: RPCServer):
        message = PingMessage(value="test")
        result = await server._handle(message=message)
        assert isinstance(result, PingResult)
        assert result.pong == "test"

    @pytest.mark.asyncio()
    async def test_handle_error(self, server: RPCServer):
        message = FailMessage()
        with pytest.raises(ValueError, match="test error"):
            await server._handle(message=message)

    @pytest.mark.asyncio()
    async def test_handle_unknown_message(self, server: RPCServer):
        class UnregisteredMessage(Message):
            pass

        with pytest.raises(RuntimeError, match="Нет хендлера"):
            await server._handle(message=UnregisteredMessage())


class TestServerCreateHandler:
    """Тесты _create_handler — точка расширения для DI."""

    def test_create_handler_default(self, server: RPCServer):
        from .conftest import PingHandler

        handler: Handler = server._create_handler(
            handler_cls=PingHandler,
            message=PingMessage(value="x"),
        )
        assert isinstance(handler, PingHandler)

    def test_create_handler_override(self):
        """Подкласс может переопределить _create_handler для DI."""

        class CustomServer(RPCServer):
            def _create_handler(
                self,
                handler_cls: type,
                message: Message,
            ) -> Handler:
                return handler_cls()  # type: ignore[call-arg]

        server = CustomServer(broker=FakeBroker())  # type: ignore[arg-type]
        message = PingMessage(value="di")
        handler = server._create_handler(
            handler_cls=type(None),  # не важно для теста
            message=message,
        )
        assert handler is None
