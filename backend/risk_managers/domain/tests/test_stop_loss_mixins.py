from decimal import Decimal

import pytest

from risk_managers.domain.risk_managers import (
    StopLossExtremumMixin,
    StopLossPercentMixin,
)
from risk_managers.domain.schemas import PositionType


class MockCandle:
    """Mock свечи для тестов."""

    def __init__(self, low, high):
        self.low = low
        self.high = high


class TestStopLossPercentMixin:
    """Тесты для StopLossPercentMixin."""

    def test_get_stop_loss_long(self):
        """Тест расчёта стоп-лосса для LONG."""
        mixin = StopLossPercentMixin(stop_loss_percent=1.0)
        price = Decimal("100.00")

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=[])
        # LONG: 100 - (100 * 1 / 100) = 99
        assert stop_loss == Decimal("99.00")

    def test_get_stop_loss_short(self):
        """Тест расчёта стоп-лосса для SHORT."""
        mixin = StopLossPercentMixin(stop_loss_percent=1.0)
        price = Decimal("100.00")

        stop_loss = mixin.get_stop_loss(PositionType.SHORT, price, candles=[])
        # SHORT: 100 + (100 * 1 / 100) = 101
        assert stop_loss == Decimal("101.00")

    def test_get_stop_loss_long_larger_percent(self):
        """Тест расчёта стоп-лосса с большим процентом."""
        mixin = StopLossPercentMixin(stop_loss_percent=5.0)
        price = Decimal("200.00")

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=[])
        # LONG: 200 - (200 * 5 / 100) = 190
        assert stop_loss == Decimal("190.00")

    def test_get_stop_loss_short_larger_percent(self):
        """Тест расчёта стоп-лосса для SHORT с большим процентом."""
        mixin = StopLossPercentMixin(stop_loss_percent=5.0)
        price = Decimal("200.00")

        stop_loss = mixin.get_stop_loss(PositionType.SHORT, price, candles=[])
        # SHORT: 200 + (200 * 5 / 100) = 210
        assert stop_loss == Decimal("210.00")

    def test_default_stop_loss_percent(self):
        """Тест дефолтного значения процента стоп-лосса."""
        mixin = StopLossPercentMixin()
        price = Decimal("100.00")

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=[])
        # Дефолт = 1.0%: 100 - 1 = 99
        assert stop_loss == Decimal("99.00")

    def test_invalid_stop_loss_percent_too_low(self):
        """Тест ошибки при слишком маленьком проценте."""
        with pytest.raises(ValueError):
            StopLossPercentMixin(stop_loss_percent=0.001)

    def test_invalid_stop_loss_percent_too_high(self):
        """Тест ошибки при слишком большом проценте."""
        with pytest.raises(ValueError):
            StopLossPercentMixin(stop_loss_percent=50.0)


class TestStopLossExtremumMixin:
    """Тесты для StopLossExtremumMixin."""

    def test_get_stop_loss_long(self):
        """Тест расчёта стоп-лосса по экстремуму для LONG."""
        mixin = StopLossExtremumMixin(extremum_candle_length=5)
        price = Decimal("100.00")
        candles = [MockCandle(low=100, high=110) for _ in range(5)]

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=candles)
        # LONG: минимум low = 100 (все свечи одинаковые)
        assert stop_loss == Decimal("100")

    def test_get_stop_loss_short(self):
        """Тест расчёта стоп-лосса по экстремуму для SHORT."""
        mixin = StopLossExtremumMixin(extremum_candle_length=5)
        price = Decimal("100.00")
        candles = [MockCandle(low=100, high=110) for _ in range(5)]

        stop_loss = mixin.get_stop_loss(PositionType.SHORT, price, candles=candles)
        # SHORT: максимум high = 110 (все свечи одинаковые)
        assert stop_loss == Decimal("110")

    def test_get_stop_loss_long_variable_candles(self):
        """Тест расчёта стоп-лосса для LONG с разными свечами."""
        candles = [
            MockCandle(low=95, high=105),
            MockCandle(low=90, high=110),
            MockCandle(low=92, high=108),
            MockCandle(low=88, high=112),
            MockCandle(low=91, high=109),
        ]
        mixin = StopLossExtremumMixin(extremum_candle_length=5)
        price = Decimal("100.00")

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=candles)
        # LONG: минимум low = 88
        assert stop_loss == Decimal("88")

    def test_get_stop_loss_short_variable_candles(self):
        """Тест расчёта стоп-лосса для SHORT с разными свечами."""
        candles = [
            MockCandle(low=95, high=105),
            MockCandle(low=90, high=110),
            MockCandle(low=92, high=108),
            MockCandle(low=88, high=112),
            MockCandle(low=91, high=109),
        ]
        mixin = StopLossExtremumMixin(extremum_candle_length=5)
        price = Decimal("100.00")

        stop_loss = mixin.get_stop_loss(PositionType.SHORT, price, candles=candles)
        # SHORT: максимум high = 112
        assert stop_loss == Decimal("112")

    def test_default_extremum_candle_length(self):
        """Тест дефолтного значения длины экстремума."""
        mixin = StopLossExtremumMixin()
        price = Decimal("100.00")
        candles = [MockCandle(low=100, high=110) for _ in range(5)]

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=candles)
        # Дефолт = 5 свечей
        assert stop_loss == Decimal("100")

    def test_get_stop_loss_no_candles(self):
        """Тест когда нет свечей."""
        mixin = StopLossExtremumMixin(extremum_candle_length=5)
        price = Decimal("100.00")

        stop_loss = mixin.get_stop_loss(PositionType.LONG, price, candles=[])
        assert stop_loss is None

    def test_invalid_extremum_candle_length_too_low(self):
        """Тест ошибки при слишком маленькой длине."""
        with pytest.raises(ValueError):
            StopLossExtremumMixin(extremum_candle_length=0)

    def test_invalid_extremum_candle_length_too_high(self):
        """Тест ошибки при слишком большой длине."""
        with pytest.raises(ValueError):
            StopLossExtremumMixin(extremum_candle_length=200)

    def test_invalid_extremum_candle_length_not_int(self):
        """Тест ошибки при нецелочисленной длине."""
        with pytest.raises(TypeError):
            StopLossExtremumMixin(extremum_candle_length=5.5)
