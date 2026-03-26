"""Тесты BusError."""

from core.utils.cqrs.base import BusError


class TestBusError:
    def test_message(self):
        error = BusError(message="fail", error_type="ValueError")
        assert str(error) == "fail"

    def test_error_type(self):
        error = BusError(message="fail", error_type="ValueError")
        assert error.error_type == "ValueError"

    def test_error_type_none(self):
        error = BusError(message="fail")
        assert error.error_type is None

    def test_is_exception(self):
        error = BusError(message="fail")
        assert isinstance(error, Exception)
