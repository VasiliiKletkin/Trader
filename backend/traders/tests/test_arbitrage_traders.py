"""
Тесты моделей ArbitrageTrader.
Фокус на query count validation и корректность ORM операций.
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.utils.types import (
    PositionStatus,
    PositionType,
)
from traders.domain import ArbitrageTrader as DomainArbitrageTrader
from traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
)


# ==================== ArbitrageTrader Model Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderModel:
    """Тесты модели ArbitrageTrader."""

    def test_str_representation(self, arbitrage_trader):
        """Тест строкового представления."""
        str_repr = str(arbitrage_trader)
        assert str(arbitrage_trader.pk) in str_repr

    def test_timeframe_property(self, arbitrage_trader):
        """Тест свойства timeframe."""
        assert arbitrage_trader.timeframe == arbitrage_trader.first_candle_source.timeframe

    def test_trading_pair_property(self, arbitrage_trader):
        """Тест свойства trading_pair."""
        assert arbitrage_trader.trading_pair == arbitrage_trader.first_candle_source.trading_pair

    def test_instantiate_returns_domain_trader(self, arbitrage_trader):
        """Тест что instantiate возвращает domain ArbitrageTrader."""
        domain_trader = arbitrage_trader.instantiate()
        assert isinstance(domain_trader, DomainArbitrageTrader)
        assert domain_trader.initial_balance == arbitrage_trader.initial_balance

    def test_get_opened_positions(
        self, arbitrage_trader, arbitrage_position, closed_arbitrage_position
    ):
        """Тест получения открытых позиций."""
        opened = arbitrage_trader.get_opened_positions()
        assert opened.count() == 1
        assert arbitrage_position in opened

    def test_get_closed_positions(
        self, arbitrage_trader, arbitrage_position, closed_arbitrage_position
    ):
        """Тест получения закрытых позиций."""
        closed = arbitrage_trader.get_closed_positions()
        assert closed.count() == 1
        assert closed_arbitrage_position in closed

    def test_get_balance_fixed(self, arbitrage_trader):
        """Тест получения баланса при фиксированном балансе."""
        arbitrage_trader.use_fixed_balance = True
        arbitrage_trader.initial_balance = Decimal("1000.00")
        arbitrage_trader.save()

        assert arbitrage_trader.get_balance() == Decimal("1000.00")


@pytest.mark.django_db
class TestArbitrageTraderPositionModel:
    """Тесты модели ArbitrageTraderPosition."""

    def test_instantiate_returns_domain_position(self, arbitrage_position):
        """Тест что instantiate возвращает domain ArbitrageTraderPosition."""
        domain_position = arbitrage_position.instantiate()
        assert domain_position.first_open_price == arbitrage_position.first_open_price
        assert domain_position.second_open_price == arbitrage_position.second_open_price

    def test_pnl_property_opened_position(self, arbitrage_position):
        """Тест PnL для открытой позиции."""
        assert arbitrage_position.pnl is None

    def test_pnl_property_closed_position(self, closed_arbitrage_position):
        """Тест PnL для закрытой позиции."""
        pnl = closed_arbitrage_position.pnl
        assert pnl is not None
        assert pnl > 0

    def test_is_closed_property(self, arbitrage_position, closed_arbitrage_position):
        """Тест свойства is_closed."""
        assert arbitrage_position.is_closed is False
        assert closed_arbitrage_position.is_closed is True

    def test_open_cost_property(self, closed_arbitrage_position):
        """Тест свойства open_cost."""
        open_cost = closed_arbitrage_position.open_cost
        expected = (Decimal("50000") + Decimal("50100")) * Decimal("0.1")
        assert open_cost == expected

    def test_close_cost_property(self, closed_arbitrage_position):
        """Тест свойства close_cost."""
        close_cost = closed_arbitrage_position.close_cost
        expected = (Decimal("50500") + Decimal("49800")) * Decimal("0.1")
        assert close_cost == expected


@pytest.mark.django_db
class TestArbitrageTraderClearData:
    """Тесты очистки данных ArbitrageTrader."""

    def test_clear_all_data(
        self, arbitrage_trader, arbitrage_signal, arbitrage_position
    ):
        """Тест очистки всех данных арбитражного трейдера."""
        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() > 0
        )
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() > 0
        )

        arbitrage_trader.clear_all_data()

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() == 0
        )
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() == 0
        )


@pytest.mark.django_db
class TestArbitrageTraderErrorModel:
    """Тесты модели ArbitrageTraderError."""

    def test_create_error(self, arbitrage_trader):
        """Тест создания ошибки."""
        error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Test error message",
            type="TestError",
            traceback="Traceback...",
        )

        assert error.trader == arbitrage_trader
        assert error.message == "Test error message"
        assert error.type == "TestError"

    def test_str_representation(self, arbitrage_trader):
        """Тест строкового представления."""
        error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Test error",
            type="TestError",
        )
        str_repr = str(error)
        assert str(arbitrage_trader.pk) in str_repr
        assert "TestError" in str_repr

    def test_instantiate_returns_domain_error(self, arbitrage_trader):
        """Тест что instantiate возвращает domain error."""
        error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Test error",
            type="TestError",
        )
        domain_error = error.instantiate()
        assert domain_error.message == error.message
        assert domain_error.type == error.type


@pytest.mark.django_db
class TestArbitrageTraderValidation:
    """Тесты валидации ArbitrageTrader."""

    def test_clean_same_exchange_clients_raises_error(
        self,
        candle_source,
        second_candle_source,
        exchange_client,
        arbitrage_strategy,
        risk_manager,
    ):
        """Тест что нельзя создать трейдера с одинаковыми клиентами."""
        from django.forms import ValidationError

        trader = ArbitrageTrader(
            first_candle_source=candle_source,
            second_candle_source=second_candle_source,
            first_exchange_client=exchange_client,
            second_exchange_client=exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError):
            trader.clean()


@pytest.mark.django_db
class TestArbitrageTraderQueryOptimization:
    """Тесты оптимизации запросов для ArbitrageTrader."""

    def test_load_positions_query_count(
        self, arbitrage_trader, arbitrage_position
    ):
        """Тест количества запросов при загрузке позиций."""
        for i in range(3):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=PositionType.LONG,
                first_type=PositionType.LONG,
                second_type=PositionType.SHORT,
                status=PositionStatus.OPENED,
                amount=Decimal("0.1"),
                first_open_price=Decimal("50000.00") + i * 100,
                second_open_price=Decimal("50100.00") + i * 100,
                opened_at=datetime.now(timezone.utc) + timedelta(hours=i),
                total_fee=Decimal("0.10"),
            )

        domain_trader = arbitrage_trader.instantiate()

        with CaptureQueriesContext(connection) as queries:
            arbitrage_trader.load(domain_trader)

        # Должно быть 2 запроса: сигналы и позиции
        assert len(queries) == 2
