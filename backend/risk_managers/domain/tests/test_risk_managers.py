from decimal import Decimal
from unittest.mock import Mock

import pytest

from risk_managers.domain.risk_managers import (
    SLExtremumTPPercentPSAllInRiskManager,
    SLExtremumTPPercentPSByRiskRiskManager,
    SLExtremumTPRiskRewardPSAllInRiskManager,
    SLExtremumTPRiskRewardPSByRiskRiskManager,
    SLPercentTPPercentPSAllInRiskManager,
    SLPercentTPPercentPSByRiskRiskManager,
    SLPercentTPRiskRewardPSAllInRiskManager,
    SLPercentTPRiskRewardPSByRiskRiskManager,
)
from risk_managers.domain.schemas import PositionType


def make_candles_with_extremums():
    """Создаёт список свечей с экстремумами."""
    candles = []
    for i in range(5):
        candle = Mock()
        candle.low = Decimal("90") + i  # 90, 91, 92, 93, 94
        candle.high = Decimal("110") + i  # 110, 111, 112, 113, 114
        candles.append(candle)
    return candles


class TestSLPercentTPPercentPSAllInRiskManager:
    """Тесты для SLPercentTPPercentPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manager = SLPercentTPPercentPSAllInRiskManager(
            stop_loss_percent=2.0, take_profit_percent=3.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """Тест расчёта размера позиции."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=[]
        )
        # AllIn: balance / price = 1000 / 100 = 10
        assert position_size == Decimal("10.0")

    def test_get_stop_loss_long(self):
        """Тест расчёта стоп-лосса для LONG."""
        stop_loss = self.manager.get_stop_loss(
            PositionType.LONG, self.price, candles=[]
        )
        # LONG: 100 - (100 * 2 / 100) = 98
        assert stop_loss == Decimal("98.00")

    def test_get_stop_loss_short(self):
        """Тест расчёта стоп-лосса для SHORT."""
        stop_loss = self.manager.get_stop_loss(
            PositionType.SHORT, self.price, candles=[]
        )
        # SHORT: 100 + (100 * 2 / 100) = 102
        assert stop_loss == Decimal("102.00")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита для LONG."""
        take_profit = self.manager.get_take_profit(
            PositionType.LONG, self.price, candles=[]
        )
        # LONG: 100 + (100 * 3 / 100) = 103
        assert take_profit == Decimal("103.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита для SHORT."""
        take_profit = self.manager.get_take_profit(
            PositionType.SHORT, self.price, candles=[]
        )
        # SHORT: 100 - (100 * 3 / 100) = 97
        assert take_profit == Decimal("97.00")


class TestSLPercentTPPercentPSByRiskRiskManager:
    """Тесты для SLPercentTPPercentPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manager = SLPercentTPPercentPSByRiskRiskManager(
            stop_loss_percent=2.0, take_profit_percent=4.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size_long(self):
        """Тест расчёта размера позиции по риску для LONG."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=[]
        )
        # stop_loss = 98, risk_per_unit = 100 - 98 = 2
        # max_risk_amount = 1000 * 1% = 10
        # position_size = 10 / 2 = 5
        assert position_size == Decimal("5.0")

    def test_calculate_position_size_short(self):
        """Тест расчёта размера позиции для SHORT."""
        manager = SLPercentTPPercentPSByRiskRiskManager(
            stop_loss_percent=5.0, take_profit_percent=10.0, max_risk_per_trade=2.0
        )
        position_size = manager.calculate_position_size(
            PositionType.SHORT, self.price, self.balance, candles=[]
        )
        # stop_loss = 105, risk_per_unit = 5
        # max_risk_amount = 1000 * 2% = 20
        # position_size = 20 / 5 = 4
        assert position_size == Decimal("4.0")


class TestSLPercentTPRiskRewardPSAllInRiskManager:
    """Тесты для SLPercentTPRiskRewardPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manager = SLPercentTPRiskRewardPSAllInRiskManager(
            stop_loss_percent=2.0, reward_risk=2.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """Тест расчёта размера позиции."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=[]
        )
        # AllIn: balance / price = 1000 / 100 = 10
        assert position_size == Decimal("10.0")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        take_profit = self.manager.get_take_profit(
            PositionType.LONG, self.price, candles=[]
        )
        # stop_loss = 98, risk = 2
        # take_profit = 100 + (2 * 2.0) = 104
        assert take_profit == Decimal("104.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            PositionType.SHORT, self.price, candles=[]
        )
        # stop_loss = 102, risk = 2
        # take_profit = 100 - (2 * 2.0) = 96
        assert take_profit == Decimal("96.00")


class TestSLPercentTPRiskRewardPSByRiskRiskManager:
    """Тесты для SLPercentTPRiskRewardPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manager = SLPercentTPRiskRewardPSByRiskRiskManager(
            stop_loss_percent=2.0, reward_risk=2.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """Тест расчёта размера позиции по риску."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=[]
        )
        # stop_loss = 98, risk_per_unit = 2
        # max_risk_amount = 1000 * 1% = 10
        # position_size = 10 / 2 = 5
        assert position_size == Decimal("5.0")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        manager = SLPercentTPRiskRewardPSByRiskRiskManager(
            stop_loss_percent=5.0, reward_risk=3.0, max_risk_per_trade=1.0
        )
        take_profit = manager.get_take_profit(
            PositionType.LONG, self.price, candles=[]
        )
        # stop_loss = 95, risk = 5
        # take_profit = 100 + (5 * 3.0) = 115
        assert take_profit == Decimal("115.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            PositionType.SHORT, self.price, candles=[]
        )
        # stop_loss = 102, risk = 2
        # take_profit = 100 - (2 * 2.0) = 96
        assert take_profit == Decimal("96.00")


class TestSLExtremumTPPercentPSAllInRiskManager:
    """Тесты для SLExtremumTPPercentPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.candles = make_candles_with_extremums()
        self.manager = SLExtremumTPPercentPSAllInRiskManager(
            extremum_candle_length=5, take_profit_percent=2.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """Тест расчёта размера позиции."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=self.candles
        )
        # AllIn: balance / price = 1000 / 100 = 10
        assert position_size == Decimal("10.0")

    def test_get_stop_loss_long(self):
        """Тест расчёта стоп-лосса по экстремуму для LONG."""
        stop_loss = self.manager.get_stop_loss(
            PositionType.LONG, self.price, candles=self.candles
        )
        # LONG: минимум low = 90
        assert stop_loss == Decimal("90")

    def test_get_stop_loss_short(self):
        """Тест расчёта стоп-лосса по экстремуму для SHORT."""
        stop_loss = self.manager.get_stop_loss(
            PositionType.SHORT, self.price, candles=self.candles
        )
        # SHORT: максимум high = 114
        assert stop_loss == Decimal("114")


class TestSLExtremumTPPercentPSByRiskRiskManager:
    """Тесты для SLExtremumTPPercentPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.candles = make_candles_with_extremums()
        self.manager = SLExtremumTPPercentPSByRiskRiskManager(
            extremum_candle_length=5, take_profit_percent=2.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size_long(self):
        """Тест расчёта размера позиции по риску для LONG."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=self.candles
        )
        # stop_loss = 90, risk_per_unit = 10
        # max_risk_amount = 1000 * 1% = 10
        # position_size = 10 / 10 = 1
        assert position_size == Decimal("1.0")

    def test_calculate_position_size_short(self):
        """Тест расчёта размера позиции для SHORT."""
        manager = SLExtremumTPPercentPSByRiskRiskManager(
            extremum_candle_length=5, take_profit_percent=2.0, max_risk_per_trade=1.4
        )
        position_size = manager.calculate_position_size(
            PositionType.SHORT, self.price, self.balance, candles=self.candles
        )
        # stop_loss = 114, risk_per_unit = 14
        # max_risk_amount = 1000 * 1.4% = 14
        # position_size = 14 / 14 = 1
        assert position_size == Decimal("1.0")


class TestSLExtremumTPRiskRewardPSAllInRiskManager:
    """Тесты для SLExtremumTPRiskRewardPSAllInRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.candles = make_candles_with_extremums()
        self.manager = SLExtremumTPRiskRewardPSAllInRiskManager(
            extremum_candle_length=5, reward_risk=2.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """Тест расчёта размера позиции."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=self.candles
        )
        # AllIn: balance / price = 1000 / 100 = 10
        assert position_size == Decimal("10.0")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        take_profit = self.manager.get_take_profit(
            PositionType.LONG, self.price, candles=self.candles
        )
        # stop_loss = 90, risk = 10
        # take_profit = 100 + (10 * 2.0) = 120
        assert take_profit == Decimal("120.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            PositionType.SHORT, self.price, candles=self.candles
        )
        # stop_loss = 114, risk = 14
        # take_profit = 100 - (14 * 2.0) = 72
        assert take_profit == Decimal("72.00")


class TestSLExtremumTPRiskRewardPSByRiskRiskManager:
    """Тесты для SLExtremumTPRiskRewardPSByRiskRiskManager."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.candles = make_candles_with_extremums()
        self.manager = SLExtremumTPRiskRewardPSByRiskRiskManager(
            extremum_candle_length=5, reward_risk=2.0, max_risk_per_trade=1.0
        )
        self.price = Decimal("100.00")
        self.balance = Decimal("1000.00")

    def test_calculate_position_size(self):
        """Тест расчёта размера позиции по риску."""
        position_size = self.manager.calculate_position_size(
            PositionType.LONG, self.price, self.balance, candles=self.candles
        )
        # stop_loss = 90, risk_per_unit = 10
        # max_risk_amount = 1000 * 1% = 10
        # position_size = 10 / 10 = 1
        assert position_size == Decimal("1.0")

    def test_get_take_profit_long(self):
        """Тест расчёта тейк-профита по risk/reward для LONG."""
        manager = SLExtremumTPRiskRewardPSByRiskRiskManager(
            extremum_candle_length=5, reward_risk=3.0, max_risk_per_trade=1.0
        )
        take_profit = manager.get_take_profit(
            PositionType.LONG, self.price, candles=self.candles
        )
        # stop_loss = 90, risk = 10
        # take_profit = 100 + (10 * 3.0) = 130
        assert take_profit == Decimal("130.00")

    def test_get_take_profit_short(self):
        """Тест расчёта тейк-профита по risk/reward для SHORT."""
        take_profit = self.manager.get_take_profit(
            PositionType.SHORT, self.price, candles=self.candles
        )
        # stop_loss = 114, risk = 14
        # take_profit = 100 - (14 * 2.0) = 72
        assert take_profit == Decimal("72.00")
