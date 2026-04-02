"""Тесты Registry."""

from core.utils.rpc.base import Registry

from .conftest import (
    FailHandler,
    NoResultHandler,
    PingHandler,
    PingMessage,
    PingResult,
)


class TestRegistryHandler:
    """Тесты декоратора @Registry.handler."""

    def test_registers_message_class(self):
        result = Registry.get_message_class(
            message_class_name="PingMessage",
        )
        assert result is PingMessage

    def test_registers_handler_class(self):
        result = Registry.get_handler_class(
            message_class_name="PingMessage",
        )
        assert result is PingHandler

    def test_registers_result_class(self):
        result = Registry.get_result_class(
            message_class_name="PingMessage",
        )
        assert result is PingResult

    def test_registers_handler_without_result(self):
        result = Registry.get_result_class(
            message_class_name="FailMessage",
        )
        assert result is None

    def test_registers_no_result_handler(self):
        handler = Registry.get_handler_class(
            message_class_name="NoResultMessage",
        )
        assert handler is NoResultHandler


class TestRegistryLookup:
    """Тесты lookup методов."""

    def test_get_message_class_unknown(self):
        result = Registry.get_message_class(
            message_class_name="UnknownMessage",
        )
        assert result is None

    def test_get_handler_class_unknown(self):
        result = Registry.get_handler_class(
            message_class_name="UnknownMessage",
        )
        assert result is None

    def test_get_result_class_unknown(self):
        result = Registry.get_result_class(
            message_class_name="UnknownMessage",
        )
        assert result is None

    def test_get_registered_handlers(self):
        handlers = Registry.get_registered_handlers()
        assert "PingMessage" in handlers
        assert handlers["PingMessage"] is PingHandler
        assert "FailMessage" in handlers
        assert handlers["FailMessage"] is FailHandler
