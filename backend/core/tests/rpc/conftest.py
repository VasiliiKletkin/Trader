"""Фикстуры для тестов CQRS-модуля."""

from typing import Any

import pytest

from core.utils.rpc.base import Handler, Message, Registry, Result
from core.utils.rpc.transport import TransportRequest, TransportResponse

# --- Тестовые Message/Result/Handler ---


class PingResult(Result):
    pong: str


class PingMessage(Message):
    value: str


class FailMessage(Message):
    pass


class NoResultMessage(Message):
    pass


@Registry.handler(PingMessage, PingResult)
class PingHandler(Handler):
    async def handle(self, message: Any) -> PingResult:
        return PingResult(pong=message.value)


@Registry.handler(FailMessage)
class FailHandler(Handler):
    async def handle(self, message: Any) -> Result | None:
        raise ValueError("test error")


@Registry.handler(NoResultMessage)
class NoResultHandler(Handler):
    async def handle(self, message: Any) -> Result | None:
        return None


# --- Фикстуры ---


@pytest.fixture()
def ping_message() -> PingMessage:
    return PingMessage(value="hello")


@pytest.fixture()
def fail_message() -> FailMessage:
    return FailMessage()


@pytest.fixture()
def no_result_message() -> NoResultMessage:
    return NoResultMessage()


@pytest.fixture()
def ping_request(ping_message: PingMessage) -> TransportRequest:
    return TransportRequest.serialize(message=ping_message)


@pytest.fixture()
def ping_response(ping_request: TransportRequest) -> TransportResponse:
    return TransportResponse.serialize(
        request=ping_request,
        result=PingResult(pong="hello"),
    )


@pytest.fixture()
def error_response(ping_request: TransportRequest) -> TransportResponse:
    return TransportResponse.serialize(
        request=ping_request,
        exception=ValueError("test error"),
    )
