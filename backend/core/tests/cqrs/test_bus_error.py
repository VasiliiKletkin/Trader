"""Тесты ошибок шины."""

from core.utils.cqrs.base import (
    BusConnectionError,
    BusError,
    BusHandlerError,
    BusTimeoutError,
)


class TestBusError:
    def test_is_exception(self):
        assert isinstance(BusError("fail"), Exception)


class TestBusHandlerError:
    def test_message(self):
        error = BusHandlerError(message="fail", error_type="ValueError")
        assert str(error) == "fail"

    def test_error_type(self):
        error = BusHandlerError(message="fail", error_type="ValueError")
        assert error.error_type == "ValueError"

    def test_error_type_none(self):
        error = BusHandlerError(message="fail")
        assert error.error_type is None

    def test_is_bus_error(self):
        assert isinstance(BusHandlerError("fail"), BusError)


class TestBusTimeoutError:
    def test_is_bus_error(self):
        assert isinstance(BusTimeoutError("timeout"), BusError)

    def test_message(self):
        error = BusTimeoutError("30с для FetchBalancesMessage")
        assert "FetchBalancesMessage" in str(error)


class TestBusConnectionError:
    def test_is_bus_error(self):
        assert isinstance(BusConnectionError("redis down"), BusError)
