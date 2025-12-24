from decimal import Decimal
import pytest
from risk_managers.domain.schemas import PositionType
from risk_managers.domain.risk_managers import (
    PositionSizeAllInMixin,
    PositionSizeByRiskMixin,
    PositionSizeLimitMixin,
    StopLossPercentMixin,
)


class MockTrader:
    """Mock трейдера для тестов."""

    def get_last_candles(self, count):
        return []


@pytest.fixture
def mock_trader():
    return MockTrader()


class TestPositionSizeAllInMixin:
    """Тесты для PositionSizeAllInMixin."""

    def test_calculate_position_size(self, mock_trader):
        """Тест расчёта позиции - весь баланс."""

        class TestAllInManager(PositionSizeAllInMixin):
            pass

        mixin = TestAllInManager()
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = mixin.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        # AllIn: balance / price = 1000 / 100 = 10
        assert size == Decimal("10.0")

    def test_calculate_position_size_with_decimal_price(self, mock_trader):
        """Тест расчёта позиции с дробной ценой."""

        class TestAllInManager(PositionSizeAllInMixin):
            pass

        mixin = TestAllInManager()
        price = Decimal("33.33")
        balance = Decimal("1000.0")

        size = mixin.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        expected = balance / price
        assert size == expected

    def test_calculate_position_size_short(self, mock_trader):
        """Тест расчёта позиции для SHORT (должен быть такой же как LONG)."""

        class TestAllInManager(PositionSizeAllInMixin):
            pass

        mixin = TestAllInManager()
        price = Decimal("50.0")
        balance = Decimal("500.0")

        size = mixin.calculate_position_size(
            mock_trader, PositionType.SHORT, price, balance
        )
        # AllIn: balance / price = 500 / 50 = 10
        assert size == Decimal("10.0")


class TestPositionSizeByRiskMixin:
    """Тесты для PositionSizeByRiskMixin."""

    def test_calculate_position_size(self, mock_trader):
        """Тест расчёта позиции по риску."""

        class TestRiskManager(StopLossPercentMixin, PositionSizeByRiskMixin):
            pass

        manager = TestRiskManager(stop_loss_percent=10.0, max_risk_per_trade=1.0)
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        # stop_loss = 100 - (100 * 10 / 100) = 90
        # risk_per_unit = 100 - 90 = 10
        # max_risk_amount = 1000 * 1% = 10
        # position_size = 10 / 10 = 1
        assert size == Decimal("1.0")

    def test_calculate_position_size_larger_risk(self, mock_trader):
        """Тест расчёта позиции с большим допустимым риском."""

        class TestRiskManager(StopLossPercentMixin, PositionSizeByRiskMixin):
            pass

        manager = TestRiskManager(stop_loss_percent=2.0, max_risk_per_trade=2.0)
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        # stop_loss = 98, risk_per_unit = 2
        # max_risk_amount = 1000 * 2% = 20
        # position_size = 20 / 2 = 10
        assert size == Decimal("10.0")

    def test_calculate_position_size_short(self, mock_trader):
        """Тест расчёта позиции для SHORT."""

        class TestRiskManager(StopLossPercentMixin, PositionSizeByRiskMixin):
            pass

        manager = TestRiskManager(stop_loss_percent=5.0, max_risk_per_trade=2.0)
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.SHORT, price, balance
        )
        # stop_loss = 100 + (100 * 5 / 100) = 105
        # risk_per_unit = 105 - 100 = 5
        # max_risk_amount = 1000 * 2% = 20
        # position_size = 20 / 5 = 4
        assert size == Decimal("4.0")


class TestPositionSizeLimitMixin:
    """Тесты для PositionSizeLimitMixin."""

    def test_no_limit_needed(self, mock_trader):
        """Тест когда лимит не нужен (позиция меньше максимума)."""

        class TestLimitedManager(PositionSizeLimitMixin, PositionSizeAllInMixin):
            pass

        manager = TestLimitedManager()
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        # AllIn = 1000 / 100 = 10, лимит = balance / price = 10
        assert size == Decimal("10.0")

    def test_limits_oversized_position(self, mock_trader):
        """Тест ограничения позиции если она больше чем balance/price."""

        class TestLimitedManager(
            StopLossPercentMixin, PositionSizeLimitMixin, PositionSizeByRiskMixin
        ):
            pass

        manager = TestLimitedManager(stop_loss_percent=0.1, max_risk_per_trade=50.0)
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        # stop_loss = 99.9, risk_per_unit = 0.1
        # max_risk_amount = 1000 * 50% = 500
        # position_size by risk = 500 / 0.1 = 5000
        # НО max_size = balance / price = 10
        # Результат ограничен до 10
        assert size == Decimal("10.0")

    def test_no_limit_needed_with_risk(self, mock_trader):
        """Тест когда позиция по риску меньше чем максимально возможная."""

        class TestLimitedManager(
            StopLossPercentMixin, PositionSizeLimitMixin, PositionSizeByRiskMixin
        ):
            pass

        manager = TestLimitedManager(stop_loss_percent=10.0, max_risk_per_trade=1.0)
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.LONG, price, balance
        )
        # position_size by risk = 1.0
        # max_size = 10
        # 1.0 < 10, лимит не применяется
        assert size == Decimal("1.0")

    def test_limit_with_short_position(self, mock_trader):
        """Тест ограничения для SHORT позиции."""

        class TestLimitedManager(
            StopLossPercentMixin, PositionSizeLimitMixin, PositionSizeByRiskMixin
        ):
            pass

        manager = TestLimitedManager(stop_loss_percent=0.05, max_risk_per_trade=100.0)
        price = Decimal("100.0")
        balance = Decimal("1000.0")

        size = manager.calculate_position_size(
            mock_trader, PositionType.SHORT, price, balance
        )
        # Позиция по риску будет очень большой, но ограничена до max_size = 10
        assert size == Decimal("10.0")
