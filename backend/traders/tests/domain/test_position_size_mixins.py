from decimal import Decimal

import pytest

from traders.domain.risk_managers import (
    PositionSizeAllInMixin,
    PositionSizeByRiskMixin,
    PositionSizeLimitMixin,
    StopLossPercentMixin,
)
from traders.domain.schemas import PositionType


class MockTrader:
    """Mock трейдера для тестов."""

    def get_last_candles(self, count):
        return []


@pytest.fixture
def mock_trader():
    return MockTrader()


class TestPositionSizeAllInMixin:
    """Тесты для PositionSizeAllInMixin: возвращает cost = balance."""

    def test_calculate_position_size(self, mock_trader):
        """AllIn возвращает cost = balance."""

        class TestAllInManager(PositionSizeAllInMixin):
            pass

        mixin = TestAllInManager()
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = mixin.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        assert size == Decimal("1000.0")

    def test_calculate_position_size_price_independent(self, mock_trader):
        """Cost не зависит от цены."""

        class TestAllInManager(PositionSizeAllInMixin):
            pass

        mixin = TestAllInManager()
        balance = Decimal("1000.0")

        size = mixin.calculate_position_size(
            mock_trader, PositionType.LONG, Decimal("33.33"), balance
        )
        assert size == balance

    def test_calculate_position_size_short(self, mock_trader):
        """SHORT даёт тот же cost, что и LONG."""

        class TestAllInManager(PositionSizeAllInMixin):
            pass

        mixin = TestAllInManager()
        size = mixin.calculate_position_size(
            mock_trader,
            PositionType.SHORT,
            Decimal("50.0"),
            Decimal("500.0"),
        )
        assert size == Decimal("500.0")


class TestPositionSizeByRiskMixin:
    """Тесты для PositionSizeByRiskMixin: cost = risk_amount * price / stop_distance."""

    def test_calculate_position_size(self, mock_trader):
        """stop=10%, risk=1%: cost = 10 * 100 / 10 = 100."""

        class TestRiskManager(StopLossPercentMixin, PositionSizeByRiskMixin):
            pass

        manager = TestRiskManager(stop_loss_percent=10.0, max_risk_per_trade=1.0)
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.LONG,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        assert size == Decimal("100")

    def test_calculate_position_size_larger_risk(self, mock_trader):
        """stop=2%, risk=2%: cost = 20 * 100 / 2 = 1000."""

        class TestRiskManager(StopLossPercentMixin, PositionSizeByRiskMixin):
            pass

        manager = TestRiskManager(stop_loss_percent=2.0, max_risk_per_trade=2.0)
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.LONG,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        assert size == Decimal("1000")

    def test_calculate_position_size_short(self, mock_trader):
        """SHORT, stop=5%, risk=2%: cost = 20 * 100 / 5 = 400."""

        class TestRiskManager(StopLossPercentMixin, PositionSizeByRiskMixin):
            pass

        manager = TestRiskManager(stop_loss_percent=5.0, max_risk_per_trade=2.0)
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.SHORT,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        assert size == Decimal("400")


class TestPositionSizeLimitMixin:
    """Тесты для PositionSizeLimitMixin: обрезает cost до balance."""

    def test_no_limit_needed(self, mock_trader):
        """AllIn уже = balance, лимит не меняет результата."""

        class TestLimitedManager(PositionSizeLimitMixin, PositionSizeAllInMixin):
            pass

        manager = TestLimitedManager()
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.LONG,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        assert size == Decimal("1000.0")

    def test_limits_oversized_position(self, mock_trader):
        """ByRisk с узким стопом даёт cost > balance → обрезается до balance."""

        class TestLimitedManager(
            StopLossPercentMixin, PositionSizeLimitMixin, PositionSizeByRiskMixin
        ):
            pass

        manager = TestLimitedManager(stop_loss_percent=0.1, max_risk_per_trade=50.0)
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.LONG,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        # cost by risk = 500 * 100 / 0.1 = 500000, обрезано до balance = 1000
        assert size == Decimal("1000.0")

    def test_no_limit_needed_with_risk(self, mock_trader):
        """cost по риску < balance — лимит не применяется."""

        class TestLimitedManager(
            StopLossPercentMixin, PositionSizeLimitMixin, PositionSizeByRiskMixin
        ):
            pass

        manager = TestLimitedManager(stop_loss_percent=10.0, max_risk_per_trade=1.0)
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.LONG,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        # cost = 10 * 100 / 10 = 100, меньше balance=1000
        assert size == Decimal("100")

    def test_limit_with_short_position(self, mock_trader):
        """SHORT: большой cost обрезается до balance."""

        class TestLimitedManager(
            StopLossPercentMixin, PositionSizeLimitMixin, PositionSizeByRiskMixin
        ):
            pass

        manager = TestLimitedManager(stop_loss_percent=0.05, max_risk_per_trade=100.0)
        size = manager.calculate_position_size(
            mock_trader,
            PositionType.SHORT,
            Decimal("100.0"),
            Decimal("1000.0"),
        )
        assert size == Decimal("1000.0")
