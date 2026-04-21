from decimal import Decimal
from unittest.mock import Mock

import pytest

from arbitrage_traders.domain.risk_managers import (
    PSAllInArbitrageRiskManager,
    PSPercentArbitrageRiskManager,
)
from traders.domain.risk_managers import (
    SLExtremumTPPercentPSAllInRiskManager,
    SLExtremumTPPercentPSByRiskRiskManager,
    SLExtremumTPRiskRewardPSAllInRiskManager,
    SLExtremumTPRiskRewardPSByRiskRiskManager,
    SLPercentTPPercentPSAllInRiskManager,
    SLPercentTPPercentPSByRiskRiskManager,
    SLPercentTPRiskRewardPSAllInRiskManager,
    SLPercentTPRiskRewardPSByRiskRiskManager,
)
from traders.domain.schemas import PositionType


class MockTrader:
    """Mock трейдера без свечей."""

    pass


class MockTraderWithCandles:
    """Mock трейдера с методом get_last_candles."""

    def __init__(self):
        self.candles = []
        for i in range(5):
            candle = Mock()
            candle.low = Decimal("90") + i  # 90, 91, 92, 93, 94
            candle.high = Decimal("110") + i  # 110, 111, 112, 113, 114
            self.candles.append(candle)

    def get_last_candles(self, count):
        return self.candles[:count]


@pytest.fixture
def mock_trader():
    """Mock трейдера без свечей (для percent-based стратегий)."""
    return MockTrader()


@pytest.fixture
def mock_trader_with_candles():
    """Mock трейдера с методом get_last_candles (для extremum-based стратегий)."""
    return MockTraderWithCandles()


class TestSLPercentTPPercentPSAllInRiskManager:
    """Тесты для SLPercentTPPercentPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader):
        self.trader = mock_trader
        self.manager = SLPercentTPPercentPSAllInRiskManager(
            stop_loss_percent=2.0, take_profit_percent=3.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """AllIn: cost = balance = 1000."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("1000.00")

    def test_get_stop_loss_long(self):
        """Тест расчёта стоп-лосса для LONG."""
        stop_loss = self.manager.get_stop_loss(
            self.trader, PositionType.LONG, self.price
        )
        # LONG: 100 - (100 * 2 / 100) = 98
        assert stop_loss == Decimal("98.00")

    def test_get_stop_loss_short(self):
        """Тест расчёта стоп-лосса для SHORT."""
        stop_loss = self.manager.get_stop_loss(
            self.trader, PositionType.SHORT, self.price
        )
        # SHORT: 100 + (100 * 2 / 100) = 102
        assert stop_loss == Decimal("102.00")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита для LONG."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.LONG, self.price
        )
        # LONG: 100 + (100 * 3 / 100) = 103
        assert take_profit == Decimal("103.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита для SHORT."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.SHORT, self.price
        )
        # SHORT: 100 - (100 * 3 / 100) = 97
        assert take_profit == Decimal("97.00")


class TestSLPercentTPPercentPSByRiskRiskManager:
    """Тесты для SLPercentTPPercentPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader):
        self.trader = mock_trader
        self.manager = SLPercentTPPercentPSByRiskRiskManager(
            stop_loss_percent=2.0, take_profit_percent=4.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size_long(self):
        """ByRisk LONG: cost = risk_amount * price / stop_distance = 10 * 100 / 2 = 500."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("500")

    def test_calculate_position_size_short(self):
        """ByRisk SHORT: cost = 20 * 100 / 5 = 400."""
        manager = SLPercentTPPercentPSByRiskRiskManager(
            stop_loss_percent=5.0, take_profit_percent=10.0, max_risk_per_trade=2.0
        )
        position_size = manager.calculate_position_size(
            self.trader, PositionType.SHORT, self.price, self.balance
        )
        assert position_size == Decimal("400")


class TestSLPercentTPRiskRewardPSAllInRiskManager:
    """Тесты для SLPercentTPRiskRewardPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader):
        self.trader = mock_trader
        self.manager = SLPercentTPRiskRewardPSAllInRiskManager(
            stop_loss_percent=2.0, reward_risk=2.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """AllIn: cost = balance = 1000."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("1000.00")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.LONG, self.price
        )
        # stop_loss = 98, risk = 2
        # take_profit = 100 + (2 * 2.0) = 104
        assert take_profit == Decimal("104.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.SHORT, self.price
        )
        # stop_loss = 102, risk = 2
        # take_profit = 100 - (2 * 2.0) = 96
        assert take_profit == Decimal("96.00")


class TestSLPercentTPRiskRewardPSByRiskRiskManager:
    """Тесты для SLPercentTPRiskRewardPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader):
        self.trader = mock_trader
        self.manager = SLPercentTPRiskRewardPSByRiskRiskManager(
            stop_loss_percent=2.0, reward_risk=2.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """ByRisk: cost = 10 * 100 / 2 = 500."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("500")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        manager = SLPercentTPRiskRewardPSByRiskRiskManager(
            stop_loss_percent=5.0, reward_risk=3.0, max_risk_per_trade=1.0
        )
        take_profit = manager.get_take_profit(
            self.trader, PositionType.LONG, self.price
        )
        # stop_loss = 95, risk = 5
        # take_profit = 100 + (5 * 3.0) = 115
        assert take_profit == Decimal("115.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.SHORT, self.price
        )
        # stop_loss = 102, risk = 2
        # take_profit = 100 - (2 * 2.0) = 96
        assert take_profit == Decimal("96.00")


class TestSLExtremumTPPercentPSAllInRiskManager:
    """Тесты для SLExtremumTPPercentPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader_with_candles):
        self.trader = mock_trader_with_candles
        self.manager = SLExtremumTPPercentPSAllInRiskManager(
            extremum_candle_length=5, take_profit_percent=2.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """AllIn: cost = balance = 1000."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("1000.00")

    def test_get_stop_loss_long(self):
        """Тест расчёта стоп-лосса по экстремуму для LONG."""
        stop_loss = self.manager.get_stop_loss(
            self.trader, PositionType.LONG, self.price
        )
        # LONG: минимум low = 90
        assert stop_loss == Decimal("90")

    def test_get_stop_loss_short(self):
        """Тест расчёта стоп-лосса по экстремуму для SHORT."""
        stop_loss = self.manager.get_stop_loss(
            self.trader, PositionType.SHORT, self.price
        )
        # SHORT: максимум high = 114
        assert stop_loss == Decimal("114")


class TestSLExtremumTPPercentPSByRiskRiskManager:
    """Тесты для SLExtremumTPPercentPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader_with_candles):
        self.trader = mock_trader_with_candles
        self.manager = SLExtremumTPPercentPSByRiskRiskManager(
            extremum_candle_length=5, take_profit_percent=2.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size_long(self):
        """ByRisk LONG: cost = 10 * 100 / 10 = 100."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("100")

    def test_calculate_position_size_short(self):
        """ByRisk SHORT: cost = 14 * 100 / 14 = 100."""
        manager = SLExtremumTPPercentPSByRiskRiskManager(
            extremum_candle_length=5, take_profit_percent=2.0, max_risk_per_trade=1.4
        )
        position_size = manager.calculate_position_size(
            self.trader, PositionType.SHORT, self.price, self.balance
        )
        assert position_size == Decimal("100")


class TestSLExtremumTPRiskRewardPSAllInRiskManager:
    """Тесты для SLExtremumTPRiskRewardPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader_with_candles):
        self.trader = mock_trader_with_candles
        self.manager = SLExtremumTPRiskRewardPSAllInRiskManager(
            extremum_candle_length=5, reward_risk=2.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """AllIn: cost = balance = 1000."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("1000.00")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.LONG, self.price
        )
        # stop_loss = 90, risk = 10
        # take_profit = 100 + (10 * 2.0) = 120
        assert take_profit == Decimal("120.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.SHORT, self.price
        )
        # stop_loss = 114, risk = 14
        # take_profit = 100 - (14 * 2.0) = 72
        assert take_profit == Decimal("72.00")


class TestSLExtremumTPRiskRewardPSByRiskRiskManager:
    """Тесты для SLExtremumTPRiskRewardPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader_with_candles):
        self.trader = mock_trader_with_candles
        self.manager = SLExtremumTPRiskRewardPSByRiskRiskManager(
            extremum_candle_length=5, reward_risk=2.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """ByRisk: cost = 10 * 100 / 10 = 100."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("100")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        manager = SLExtremumTPRiskRewardPSByRiskRiskManager(
            extremum_candle_length=5, reward_risk=3.0, max_risk_per_trade=1.0
        )
        take_profit = manager.get_take_profit(
            self.trader, PositionType.LONG, self.price
        )
        # stop_loss = 90, risk = 10
        # take_profit = 100 + (10 * 3.0) = 130
        assert take_profit == Decimal("130.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            self.trader, PositionType.SHORT, self.price
        )
        # stop_loss = 114, risk = 14
        # take_profit = 100 - (14 * 2.0) = 72
        assert take_profit == Decimal("72.00")


# --- Арбитражные риск-менеджеры ---


class TestPSAllInArbitrageRiskManager:
    """Тесты для PSAllInArbitrageRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader):
        self.trader = mock_trader
        self.manager = PSAllInArbitrageRiskManager()
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size_long(self):
        """AllIn: cost = balance = 1000."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("1000.00")

    def test_calculate_position_size_short(self):
        """AllIn SHORT: cost = balance = 1000."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.SHORT, self.price, self.balance
        )
        assert position_size == Decimal("1000.00")

    def test_no_stop_loss_method(self):
        """Тест что нет метода get_stop_loss."""
        assert not hasattr(self.manager, "get_stop_loss")

    def test_no_take_profit_method(self):
        """Тест что нет метода get_take_profit."""
        assert not hasattr(self.manager, "get_take_profit")


class TestPSPercentArbitrageRiskManager:
    """Тесты для PSPercentArbitrageRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self, mock_trader):
        self.trader = mock_trader
        self.manager = PSPercentArbitrageRiskManager(position_size_percent=50.0)
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size_long(self):
        """Percent 50%: cost = 1000 * 50 / 100 = 500."""
        position_size = self.manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("500")

    def test_calculate_position_size_full_balance(self):
        """Percent 100%: cost = balance = 1000."""
        manager = PSPercentArbitrageRiskManager(position_size_percent=100.0)
        position_size = manager.calculate_position_size(
            self.trader, PositionType.LONG, self.price, self.balance
        )
        assert position_size == Decimal("1000")

    def test_calculate_position_size_small_percent(self):
        """Percent 10%: cost = 1000 * 10 / 100 = 100."""
        manager = PSPercentArbitrageRiskManager(position_size_percent=10.0)
        position_size = manager.calculate_position_size(
            self.trader, PositionType.SHORT, self.price, self.balance
        )
        assert position_size == Decimal("100")

    def test_invalid_percent_too_low(self):
        """Тест что слишком малый процент вызывает ошибку."""
        with pytest.raises(ValueError):
            PSPercentArbitrageRiskManager(position_size_percent=0.0)

    def test_invalid_percent_too_high(self):
        """Тест что слишком большой процент вызывает ошибку."""
        with pytest.raises(ValueError):
            PSPercentArbitrageRiskManager(position_size_percent=101.0)

    def test_no_stop_loss_method(self):
        """Тест что нет метода get_stop_loss."""
        assert not hasattr(self.manager, "get_stop_loss")

    def test_no_take_profit_method(self):
        """Тест что нет метода get_take_profit."""
        assert not hasattr(self.manager, "get_take_profit")
