"""
Тесты доменных риск-менеджеров arbitrage_traders.
Фокус: чистая математика calculate_position_size, валидация.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from arbitrage_traders.domain.risk_managers import (
    ArbitrageRiskManagerRegistry,
    PSAllInArbitrageRiskManager,
    PSPercentArbitrageRiskManager,
)
from arbitrage_traders.domain.risk_managers.base import AbstractArbitrageRiskManager
from arbitrage_traders.domain.schemas import PositionType

# ==================== Helpers ====================


def _calc(rm, price=Decimal("100"), balance=Decimal("1000")):
    """Вызывает calculate_position_size с моковым трейдером."""
    trader = MagicMock()
    return rm.calculate_position_size(
        trader=trader,
        position_type=PositionType.LONG,
        price=price,
        balance=balance,
    )


# ==================== PositionSizeAllInMixin ====================


class TestPositionSizeAllInMixin:
    """Тесты миксина AllIn: balance / price."""

    def test_basic_calculation(self, risk_manager_allin):
        """balance=1000, price=100 → 10."""
        assert _calc(risk_manager_allin) == Decimal("10")

    def test_large_balance_small_price(self, risk_manager_allin):
        """Большой баланс, маленькая цена → большой размер."""
        result = _calc(
            risk_manager_allin, price=Decimal("0.01"), balance=Decimal("10000")
        )
        assert result == Decimal("1000000")

    def test_small_balance_large_price(self, risk_manager_allin):
        """Маленький баланс, большая цена → маленький размер."""
        result = _calc(
            risk_manager_allin, price=Decimal("50000"), balance=Decimal("100")
        )
        assert result == Decimal("0.002")


# ==================== PositionSizePercentMixin ====================


class TestPositionSizePercentMixin:
    """Тесты миксина Percent: (balance * pct / 100) / price."""

    def test_basic_calculation(self, risk_manager_percent):
        """50%, balance=1000, price=100 → 5."""
        result = _calc(risk_manager_percent)
        assert result == Decimal("5")

    def test_fifty_percent_is_half_of_allin(
        self, risk_manager_allin, risk_manager_percent
    ):
        """50% даёт половину от AllIn."""
        allin = _calc(risk_manager_allin)
        percent = _calc(risk_manager_percent)
        assert percent == allin / 2

    def test_hundred_percent_equals_allin(self, risk_manager_allin):
        """100% даёт тот же результат что AllIn."""
        rm100 = PSPercentArbitrageRiskManager(position_size_percent=100.0)
        allin = _calc(risk_manager_allin)
        percent = _calc(rm100)
        assert percent == allin

    def test_validation_too_low(self):
        """pct < 0.1 → ValueError."""
        with pytest.raises(ValueError):
            PSPercentArbitrageRiskManager(position_size_percent=0.05)

    def test_validation_too_high(self):
        """pct > 100 → ValueError."""
        with pytest.raises(ValueError):
            PSPercentArbitrageRiskManager(position_size_percent=101.0)


# ==================== PSAllInArbitrageRiskManager ====================


class TestPSAllInArbitrageRiskManager:
    """Тесты конкретного класса PSAllInArbitrageRiskManager."""

    def test_is_subclass_of_abstract(self):
        """Наследует AbstractArbitrageRiskManager."""
        assert issubclass(PSAllInArbitrageRiskManager, AbstractArbitrageRiskManager)

    def test_registered_in_registry(self):
        """Зарегистрирован в ArbitrageRiskManagerRegistry."""
        cls = ArbitrageRiskManagerRegistry.get_class(
            PSAllInArbitrageRiskManager.__name__
        )
        assert cls is PSAllInArbitrageRiskManager

    def test_calculate_delegates_to_mixin(self, risk_manager_allin):
        """calculate_position_size делегирует AllIn миксину."""
        result = _calc(risk_manager_allin, price=Decimal("50"), balance=Decimal("500"))
        assert result == Decimal("10")  # 500 / 50


# ==================== PSPercentArbitrageRiskManager ====================


class TestPSPercentArbitrageRiskManager:
    """Тесты конкретного класса PSPercentArbitrageRiskManager."""

    def test_is_subclass_of_abstract(self):
        """Наследует AbstractArbitrageRiskManager."""
        assert issubclass(PSPercentArbitrageRiskManager, AbstractArbitrageRiskManager)

    def test_registered_in_registry(self):
        """Зарегистрирован в ArbitrageRiskManagerRegistry."""
        cls = ArbitrageRiskManagerRegistry.get_class(
            PSPercentArbitrageRiskManager.__name__
        )
        assert cls is PSPercentArbitrageRiskManager

    def test_default_position_size_percent(self):
        """Дефолтный position_size_percent = 100.0."""
        rm = PSPercentArbitrageRiskManager()
        assert rm.position_size_percent == Decimal("100.0")

    def test_calculate_delegates_to_mixin(self, risk_manager_percent):
        """calculate_position_size: 50%, price=200, balance=1000 → 2.5."""
        result = _calc(
            risk_manager_percent, price=Decimal("200"), balance=Decimal("1000")
        )
        assert result == Decimal("2.5")  # (1000 * 50 / 100) / 200
