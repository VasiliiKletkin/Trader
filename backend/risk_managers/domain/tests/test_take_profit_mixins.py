from decimal import Decimal

import pytest

from risk_managers.domain.risk_managers import (
    StopLossPercentMixin,
    TakeProfitPercentMixin,
    TakeProfitRiskRewardMixin,
)
from risk_managers.domain.schemas import PositionType


class TestTakeProfitPercentMixin:
    """Тесты для TakeProfitPercentMixin."""

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита для LONG."""
        mixin = TakeProfitPercentMixin(take_profit_percent=2.0)
        price = Decimal("100.00")

        take_profit = mixin.get_take_profit(PositionType.LONG, price, candles=[])
        # LONG: 100 + (100 * 2 / 100) = 102
        assert take_profit == Decimal("102.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита для SHORT."""
        mixin = TakeProfitPercentMixin(take_profit_percent=2.0)
        price = Decimal("100.00")

        take_profit = mixin.get_take_profit(PositionType.SHORT, price, candles=[])
        # SHORT: 100 - (100 * 2 / 100) = 98
        assert take_profit == Decimal("98.00")

    def test_get_take_profit_long_larger_percent(self):
        """Тест расчёта тейк-профита с большим процентом."""
        mixin = TakeProfitPercentMixin(take_profit_percent=10.0)
        price = Decimal("200.00")

        take_profit = mixin.get_take_profit(PositionType.LONG, price, candles=[])
        # LONG: 200 + (200 * 10 / 100) = 220
        assert take_profit == Decimal("220.00")

    def test_get_take_profit_short_larger_percent(self):
        """Тест расчёта тейк-профита для SHORT с большим процентом."""
        mixin = TakeProfitPercentMixin(take_profit_percent=10.0)
        price = Decimal("200.00")

        take_profit = mixin.get_take_profit(PositionType.SHORT, price, candles=[])
        # SHORT: 200 - (200 * 10 / 100) = 180
        assert take_profit == Decimal("180.00")

    def test_default_take_profit_percent(self):
        """Тест дефолтного значения процента тейк-профита."""
        mixin = TakeProfitPercentMixin()
        price = Decimal("100.00")

        take_profit = mixin.get_take_profit(PositionType.LONG, price, candles=[])
        # Дефолт = 2.0%: 100 + 2 = 102
        assert take_profit == Decimal("102.00")

    def test_invalid_take_profit_percent_too_low(self):
        """Тест ошибки при слишком маленьком проценте."""
        with pytest.raises(ValueError):
            TakeProfitPercentMixin(take_profit_percent=0.001)

    def test_invalid_take_profit_percent_too_high(self):
        """Тест ошибки при слишком большом проценте."""
        with pytest.raises(ValueError):
            TakeProfitPercentMixin(take_profit_percent=100.0)

    def test_invalid_take_profit_percent_not_number(self):
        """Тест ошибки при нечисловом значении."""
        with pytest.raises(TypeError):
            TakeProfitPercentMixin(take_profit_percent="2.0")


class TestTakeProfitRiskRewardMixin:
    """Тесты для TakeProfitRiskRewardMixin."""

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""

        class TestManager(StopLossPercentMixin, TakeProfitRiskRewardMixin):
            pass

        manager = TestManager(stop_loss_percent=5.0, reward_risk=2.0)
        price = Decimal("100.00")

        take_profit = manager.get_take_profit(PositionType.LONG, price, candles=[])
        # stop_loss = 95, risk = 5
        # take_profit = 100 + (5 * 2.0) = 110
        assert take_profit == Decimal("110.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""

        class TestManager(StopLossPercentMixin, TakeProfitRiskRewardMixin):
            pass

        manager = TestManager(stop_loss_percent=5.0, reward_risk=2.0)
        price = Decimal("100.00")

        take_profit = manager.get_take_profit(PositionType.SHORT, price, candles=[])
        # stop_loss = 105, risk = 5
        # take_profit = 100 - (5 * 2.0) = 90
        assert take_profit == Decimal("90.00")

    def test_get_take_profit_different_reward_risk(self):
        """Тест расчёта тейк-профита с другим reward/risk."""

        class TestManager(StopLossPercentMixin, TakeProfitRiskRewardMixin):
            pass

        manager = TestManager(stop_loss_percent=2.0, reward_risk=3.0)
        price = Decimal("100.00")

        take_profit = manager.get_take_profit(PositionType.LONG, price, candles=[])
        # stop_loss = 98, risk = 2
        # take_profit = 100 + (2 * 3.0) = 106
        assert take_profit == Decimal("106.00")

    def test_get_take_profit_short_different_reward_risk(self):
        """Тест расчёта тейк-профита для SHORT с другим reward/risk."""

        class TestManager(StopLossPercentMixin, TakeProfitRiskRewardMixin):
            pass

        manager = TestManager(stop_loss_percent=4.0, reward_risk=1.5)
        price = Decimal("100.00")

        take_profit = manager.get_take_profit(PositionType.SHORT, price, candles=[])
        # stop_loss = 104, risk = 4
        # take_profit = 100 - (4 * 1.5) = 94
        assert take_profit == Decimal("94.00")

    def test_default_reward_risk(self):
        """Тест дефолтного значения reward/risk."""

        class TestManager(StopLossPercentMixin, TakeProfitRiskRewardMixin):
            pass

        manager = TestManager(stop_loss_percent=5.0)
        price = Decimal("100.00")

        take_profit = manager.get_take_profit(PositionType.LONG, price, candles=[])
        # Дефолт reward_risk = 2.0
        # stop_loss = 95, risk = 5
        # take_profit = 100 + (5 * 2.0) = 110
        assert take_profit == Decimal("110.00")

    def test_invalid_reward_risk_too_low(self):
        """Тест ошибки при слишком маленьком reward/risk."""
        with pytest.raises(ValueError):
            TakeProfitRiskRewardMixin(reward_risk=0.001)

    def test_invalid_reward_risk_too_high(self):
        """Тест ошибки при слишком большом reward/risk."""
        with pytest.raises(ValueError):
            TakeProfitRiskRewardMixin(reward_risk=20.0)
