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
    def test_str_with_error_type(self):
        error = BusHandlerError(error_message="fail", error_type="ValueError")
        assert str(error) == "fail"

    def test_str_without_error_type(self):
        error = BusHandlerError(error_message="fail")
        assert str(error) == "fail"

    def test_error_type(self):
        error = BusHandlerError(error_message="fail", error_type="ValueError")
        assert error.error_type == "ValueError"

    def test_error_message(self):
        error = BusHandlerError(error_message="fail")
        assert error.error_message == "fail"

    def test_is_bus_error(self):
        assert isinstance(BusHandlerError(error_message="fail"), BusError)


class TestBusTimeoutError:
    def test_is_bus_error(self):
        assert isinstance(BusTimeoutError("timeout"), BusError)

    def test_message(self):
        error = BusTimeoutError("30с для FetchBalancesMessage")
        assert "FetchBalancesMessage" in str(error)


class TestBusConnectionError:
    def test_is_bus_error(self):
        assert isinstance(BusConnectionError("redis down"), BusError)
