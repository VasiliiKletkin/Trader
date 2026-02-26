"""
Тесты CrossSpreadArbitrageStrategy доменного слоя.
Фокус: валидация __init__, get_signal, position_should_be_closed.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from arbitrage_traders.domain.schemas import (
    ArbitrageCandle,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    CrossSpreadArbitrageData,
    PositionStatus,
    PositionType,
    SignalType,
)
from arbitrage_traders.domain.strategies import (
    ArbitrageStrategyRegistry,
    CrossSpreadArbitrageStrategy,
)
from arbitrage_traders.domain.strategies.base import AbstractArbitrageStrategy
from exchanges.domain import ExchangeCandle

# ==================== Helpers ====================


def _candle(close: Decimal, candle_id: int = 1) -> ExchangeCandle:
    """Создаёт ExchangeCandle с заданной close ценой."""
    ts = int(datetime(2024, 1, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
    return ExchangeCandle(
        id=candle_id,
        dt_unix=ts,
        open=close - Decimal("1"),
        high=close + Decimal("1"),
        low=close - Decimal("2"),
        close=close,
        volume=Decimal("100"),
    )


@pytest.fixture
def strategy() -> CrossSpreadArbitrageStrategy:
    """Стратегия: open_threshold=0.4, close_threshold=0.4."""
    return CrossSpreadArbitrageStrategy(open_threshold=0.4, close_threshold=0.4)


# ==================== __init__ ====================


class TestCrossSpreadArbitrageStrategyInit:
    """Тесты инициализации CrossSpreadArbitrageStrategy."""

    def test_default_values(self):
        """Дефолтные значения: open_threshold=0.4, close_threshold=0.4."""
        s = CrossSpreadArbitrageStrategy()
        assert s.open_threshold == 0.4
        assert s.close_threshold == 0.4

    def test_custom_values(self):
        """Кастомные значения сохраняются."""
        s = CrossSpreadArbitrageStrategy(open_threshold=1.0, close_threshold=0.5)
        assert s.open_threshold == 1.0
        assert s.close_threshold == 0.5

    def test_open_threshold_below_min_raises(self):
        """open_threshold < MIN → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(open_threshold=0.01)

    def test_open_threshold_above_max_raises(self):
        """open_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(open_threshold=11.0)

    def test_close_threshold_below_min_raises(self):
        """close_threshold < MIN → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(close_threshold=0.01)

    def test_close_threshold_above_max_raises(self):
        """close_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(close_threshold=11.0)

    def test_non_numeric_type_raises(self):
        """Нечисловой тип → TypeError."""
        with pytest.raises(TypeError):
            CrossSpreadArbitrageStrategy(open_threshold="abc")

    def test_is_subclass_of_abstract(self):
        """Наследует AbstractArbitrageStrategy."""
        assert issubclass(CrossSpreadArbitrageStrategy, AbstractArbitrageStrategy)

    def test_registered_in_registry(self):
        """Зарегистрирован в ArbitrageStrategyRegistry."""
        cls = ArbitrageStrategyRegistry.get_class(CrossSpreadArbitrageStrategy.__name__)
        assert cls is CrossSpreadArbitrageStrategy

    def test_param_constraints(self):
        """PARAM_CONSTRAINTS содержит оба порога."""
        assert "open_threshold" in CrossSpreadArbitrageStrategy.PARAM_CONSTRAINTS
        assert "close_threshold" in CrossSpreadArbitrageStrategy.PARAM_CONSTRAINTS


# ==================== get_signal ====================


class TestCrossSpreadArbitrageStrategyGetSignal:
    """Тесты get_signal: генерация торгового сигнала."""

    def test_buy_signal_when_first_cheaper(self, strategy):
        """Спред < -open_threshold → BUY left, SELL right."""
        # spread = (99.5 - 100) / 100 * 100 = -0.5% < -0.4%
        candle = ArbitrageCandle(
            left=_candle(Decimal("99.50")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.BUY
        assert signal.right_type == SignalType.SELL

    def test_sell_signal_when_first_expensive(self, strategy):
        """Спред > +open_threshold → SELL left, BUY right."""
        # spread = (100.5 - 100) / 100 * 100 = +0.5% > +0.4%
        candle = ArbitrageCandle(
            left=_candle(Decimal("100.50")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.SELL
        assert signal.right_type == SignalType.BUY

    def test_wait_when_spread_within_threshold(self, strategy):
        """|Спред| < open_threshold → WAIT."""
        # spread = (100.2 - 100) / 100 * 100 = +0.2% < 0.4%
        candle = ArbitrageCandle(
            left=_candle(Decimal("100.20")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_wait_at_exact_positive_boundary(self, strategy):
        """Спред ровно = +open_threshold → WAIT (строгое >)."""
        # spread = (100.4 - 100) / 100 * 100 = +0.4%
        candle = ArbitrageCandle(
            left=_candle(Decimal("100.40")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT

    def test_wait_at_exact_negative_boundary(self, strategy):
        """Спред ровно = -open_threshold → WAIT (строгое <)."""
        # spread = (99.6 - 100) / 100 * 100 = -0.4%
        candle = ArbitrageCandle(
            left=_candle(Decimal("99.60")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT

    def test_signal_data_contains_spread(self, strategy):
        """signal.data содержит spread/price_first/price_second."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("102"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        data = CrossSpreadArbitrageData(**signal.data)
        assert data.price_first == pytest.approx(100.0)
        assert data.price_second == pytest.approx(102.0)
        assert isinstance(data.spread, float)

    def test_zero_second_price_returns_wait(self, strategy):
        """Нулевая цена second → WAIT (error handling)."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("0"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_signal_prices_from_candles(self, strategy):
        """left_price/right_price из close свечей."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("99.50")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_price == Decimal("99.5")
        assert signal.right_price == Decimal("100")


# ==================== position_should_be_closed ====================


class TestCrossSpreadArbitrageStrategyPositionShouldBeClosed:
    """Тесты position_should_be_closed: закрытие при переходе спреда через ноль."""

    def _make_signal_with_spread(self, spread: float) -> ArbitrageTraderSignal:
        left_candle = _candle(Decimal("100"))
        right_candle = _candle(Decimal("100"), candle_id=2)
        return ArbitrageTraderSignal(
            timestamp=left_candle.timestamp,
            left_price=Decimal("100"),
            right_price=Decimal("100"),
            left_type=SignalType.WAIT,
            right_type=SignalType.WAIT,
            left_candle=left_candle,
            right_candle=right_candle,
            data=CrossSpreadArbitrageData(
                spread=spread, price_first=100.0, price_second=100.0
            ).model_dump(),
        )

    def _make_position(self, pos_type: PositionType) -> ArbitrageTraderPosition:
        return ArbitrageTraderPosition(
            type=pos_type,
            left_type=pos_type,
            right_type=(
                PositionType.SHORT
                if pos_type == PositionType.LONG
                else PositionType.LONG
            ),
            status=PositionStatus.OPENED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            right_open_price=Decimal("100"),
        )

    def test_long_close_when_spread_crossed_to_positive(self, strategy):
        """LONG: spread >= +close_threshold → True (спред перешёл на другую сторону)."""
        signal = self._make_signal_with_spread(0.5)  # >= +0.4
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_long_keep_when_spread_still_negative(self, strategy):
        """LONG: spread < +close_threshold → False."""
        signal = self._make_signal_with_spread(-0.2)  # спред ещё отрицательный
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_long_keep_when_spread_near_zero(self, strategy):
        """LONG: spread = 0 (< +close_threshold) → False (ещё не перешёл)."""
        signal = self._make_signal_with_spread(0.0)
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_long_close_at_exact_boundary(self, strategy):
        """LONG: spread = +close_threshold → True (>=)."""
        signal = self._make_signal_with_spread(0.4)  # == +0.4
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_short_close_when_spread_crossed_to_negative(self, strategy):
        """SHORT: spread <= -close_threshold → True (спред перешёл на другую сторону)."""
        signal = self._make_signal_with_spread(-0.5)  # <= -0.4
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_short_keep_when_spread_still_positive(self, strategy):
        """SHORT: spread > -close_threshold → False."""
        signal = self._make_signal_with_spread(0.2)  # спред ещё положительный
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_short_keep_when_spread_near_zero(self, strategy):
        """SHORT: spread = 0 (> -close_threshold) → False."""
        signal = self._make_signal_with_spread(0.0)
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_short_close_at_exact_boundary(self, strategy):
        """SHORT: spread = -close_threshold → True (<=)."""
        signal = self._make_signal_with_spread(-0.4)  # == -0.4
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_invalid_data_returns_false(self, strategy):
        """Невалидные data → False."""
        left_candle = _candle(Decimal("100"))
        right_candle = _candle(Decimal("100"), candle_id=2)
        signal = ArbitrageTraderSignal(
            timestamp=left_candle.timestamp,
            left_price=Decimal("100"),
            right_price=Decimal("100"),
            left_type=SignalType.WAIT,
            right_type=SignalType.WAIT,
            left_candle=left_candle,
            right_candle=right_candle,
            data={"invalid": "data"},
        )
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False
