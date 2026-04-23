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
    """Стратегия: open_threshold=0.004, close_threshold=0.004."""
    return CrossSpreadArbitrageStrategy(open_threshold=0.004, close_threshold=0.004)


# ==================== __init__ ====================


class TestCrossSpreadArbitrageStrategyInit:
    """Тесты инициализации CrossSpreadArbitrageStrategy."""

    def test_default_values(self):
        """Дефолтные значения соответствуют константам класса."""
        s = CrossSpreadArbitrageStrategy()
        assert s.open_threshold == CrossSpreadArbitrageStrategy.OPEN_THRESHOLD_DEFAULT
        assert s.close_threshold == CrossSpreadArbitrageStrategy.CLOSE_THRESHOLD_DEFAULT

    def test_custom_values(self):
        """Кастомные значения сохраняются."""
        s = CrossSpreadArbitrageStrategy(open_threshold=0.01, close_threshold=0.005)
        assert s.open_threshold == 0.01
        assert s.close_threshold == 0.005

    def test_open_threshold_below_min_raises(self):
        """open_threshold < MIN → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(open_threshold=-0.01)

    def test_open_threshold_above_max_raises(self):
        """open_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(open_threshold=0.2)

    def test_close_threshold_below_min_raises(self):
        """close_threshold < MIN → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(close_threshold=-0.01)

    def test_close_threshold_above_max_raises(self):
        """close_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            CrossSpreadArbitrageStrategy(close_threshold=0.2)

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
        """spread < 1 - open_threshold → BUY left, SELL right."""
        # 99.50/100 = 0.995 < 1 - 0.004 = 0.996
        candle = ArbitrageCandle(
            left=_candle(Decimal("99.50")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.BUY
        assert signal.right_type == SignalType.SELL

    def test_sell_signal_when_first_expensive(self, strategy):
        """spread > 1 + open_threshold → SELL left, BUY right."""
        # 100.50/100 = 1.005 > 1 + 0.004 = 1.004
        candle = ArbitrageCandle(
            left=_candle(Decimal("100.50")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.SELL
        assert signal.right_type == SignalType.BUY

    def test_wait_when_spread_within_threshold(self, strategy):
        """1 - open_threshold <= spread <= 1 + open_threshold → WAIT."""
        # 100.20/100 = 1.002 < 1.004
        candle = ArbitrageCandle(
            left=_candle(Decimal("100.20")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_wait_at_exact_positive_boundary(self, strategy):
        """spread ровно = 1 + open_threshold → WAIT (строгое >)."""
        # 100.40/100 = 1.004 == 1 + 0.004
        candle = ArbitrageCandle(
            left=_candle(Decimal("100.40")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT

    def test_wait_at_exact_negative_boundary(self, strategy):
        """spread ровно = 1 - open_threshold → WAIT (строгое <)."""
        # 99.60/100 = 0.996 == 1 - 0.004
        candle = ArbitrageCandle(
            left=_candle(Decimal("99.60")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        assert signal.left_type == SignalType.WAIT

    def test_signal_data_contains_spread(self, strategy):
        """signal.data содержит spread/left_price/right_price."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("102"), candle_id=2),
        )
        signal = strategy.get_signal(MagicMock(), candle)
        data = CrossSpreadArbitrageData(**signal.data)
        assert data.left_price == pytest.approx(100.0)
        assert data.right_price == pytest.approx(102.0)
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
    """Тесты position_should_be_closed: закрытие при переходе спреда через паритет."""

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
                spread=spread, left_price=100.0, right_price=100.0
            ).model_dump(),
        )

    def _make_position(self, pos_type: PositionType) -> ArbitrageTraderPosition:
        return ArbitrageTraderPosition(
            left_type=pos_type,
            right_type=(
                PositionType.SHORT
                if pos_type == PositionType.LONG
                else PositionType.LONG
            ),
            status=PositionStatus.OPENED,
            left_open_price=Decimal("100"),
            right_open_price=Decimal("100"),
            left_open_amount=Decimal("1.0"),
            right_open_amount=Decimal("1.0"),
            left_open_cost=Decimal("100"),
            right_open_cost=Decimal("100"),
        )

    def test_long_close_when_spread_crossed_to_positive(self, strategy):
        """LONG: spread >= 1 + close_threshold → True."""
        signal = self._make_signal_with_spread(1.005)  # >= 1.004
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_long_keep_when_spread_still_negative(self, strategy):
        """LONG: spread < 1 + close_threshold → False."""
        signal = self._make_signal_with_spread(0.998)  # спред ещё ниже паритета
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_long_keep_when_spread_at_parity(self, strategy):
        """LONG: spread = 1.0 (< 1 + close_threshold) → False."""
        signal = self._make_signal_with_spread(1.0)
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_long_close_at_exact_boundary(self, strategy):
        """LONG: spread = 1 + close_threshold → True (>=)."""
        signal = self._make_signal_with_spread(1.004)  # == 1 + 0.004
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_short_close_when_spread_crossed_to_negative(self, strategy):
        """SHORT: spread <= 1 - close_threshold → True."""
        signal = self._make_signal_with_spread(0.995)  # <= 0.996
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_short_keep_when_spread_still_positive(self, strategy):
        """SHORT: spread > 1 - close_threshold → False."""
        signal = self._make_signal_with_spread(1.002)  # спред ещё выше паритета
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_short_keep_when_spread_at_parity(self, strategy):
        """SHORT: spread = 1.0 (> 1 - close_threshold) → False."""
        signal = self._make_signal_with_spread(1.0)
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_short_close_at_exact_boundary(self, strategy):
        """SHORT: spread = 1 - close_threshold → True (<=)."""
        signal = self._make_signal_with_spread(0.996)  # == 1 - 0.004
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
