"""
Тесты SimpleArbitrageStrategy доменного слоя.
Фокус: валидация __init__, calculate_spread, get_signal, position_should_be_closed.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from arbitrage_traders.domain.schemas import (
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    PositionStatus,
    PositionType,
    SignalType,
    SimpleArbitrageData,
)
from arbitrage_traders.domain.strategies import (
    ArbitrageStrategyRegistry,
    SimpleArbitrageStrategy,
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


# ==================== __init__ ====================


class TestSimpleArbitrageStrategyInit:
    """Тесты инициализации SimpleArbitrageStrategy."""

    def test_default_values(self):
        """Дефолтные значения: open_threshold=1.0, close_threshold=0.2."""
        s = SimpleArbitrageStrategy()
        assert s.open_threshold == 1.0
        assert s.close_threshold == 0.2

    def test_custom_values(self):
        """Кастомные значения сохраняются."""
        s = SimpleArbitrageStrategy(open_threshold=3.0, close_threshold=1.5)
        assert s.open_threshold == 3.0
        assert s.close_threshold == 1.5

    def test_open_threshold_below_min_raises(self):
        """open_threshold < MIN → ValueError."""
        with pytest.raises(ValueError):
            SimpleArbitrageStrategy(open_threshold=0.05)

    def test_open_threshold_above_max_raises(self):
        """open_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            SimpleArbitrageStrategy(open_threshold=11.0)

    def test_close_threshold_invalid_raises(self):
        """close_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            SimpleArbitrageStrategy(close_threshold=6.0)

    def test_non_numeric_type_raises(self):
        """Нечисловой тип → TypeError."""
        with pytest.raises(TypeError):
            SimpleArbitrageStrategy(open_threshold="abc")

    def test_is_subclass_of_abstract(self):
        """Наследует AbstractArbitrageStrategy."""
        assert issubclass(SimpleArbitrageStrategy, AbstractArbitrageStrategy)

    def test_registered_in_registry(self):
        """Зарегистрирован в ArbitrageStrategyRegistry."""
        cls = ArbitrageStrategyRegistry.get_class(SimpleArbitrageStrategy.__name__)
        assert cls is SimpleArbitrageStrategy


# ==================== calculate_spread ====================


class TestSimpleArbitrageStrategyCalculateSpread:
    """Тесты calculate_spread: (first - second) / second * 100."""

    def test_same_prices_zero_spread(self, strategy):
        """Одинаковые цены → 0."""
        left = _candle(Decimal("100"))
        right = _candle(Decimal("100"), candle_id=2)
        assert strategy.calculate_spread(left, right) == 0.0

    def test_first_more_expensive_positive_spread(self, strategy):
        """Первая дороже → положительный спред."""
        left = _candle(Decimal("100"))
        right = _candle(Decimal("98"), candle_id=2)
        spread = strategy.calculate_spread(left, right)
        assert spread == pytest.approx(2.0408, rel=0.01)

    def test_first_cheaper_negative_spread(self, strategy):
        """Первая дешевле → отрицательный спред."""
        left = _candle(Decimal("98"))
        right = _candle(Decimal("100"), candle_id=2)
        spread = strategy.calculate_spread(left, right)
        assert spread == pytest.approx(-2.0, rel=0.01)

    def test_zero_second_price_raises(self, strategy):
        """Нулевая цена второй биржи → ValueError."""
        left = _candle(Decimal("100"))
        right = _candle(Decimal("0"), candle_id=2)
        with pytest.raises(ValueError):
            strategy.calculate_spread(left, right)

    def test_large_price_difference(self, strategy):
        """Большая разница цен → корректный процент."""
        left = _candle(Decimal("200"))
        right = _candle(Decimal("100"), candle_id=2)
        spread = strategy.calculate_spread(left, right)
        assert spread == pytest.approx(100.0, rel=0.01)


# ==================== get_signal ====================


class TestSimpleArbitrageStrategyGetSignal:
    """Тесты get_signal: генерация торгового сигнала."""

    def test_buy_signal_when_first_cheaper(self, strategy):
        """Спред < -open_threshold → BUY left, SELL right."""
        left = _candle(Decimal("98"))
        right = _candle(Decimal("100"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_type == SignalType.BUY
        assert signal.right_type == SignalType.SELL

    def test_sell_signal_when_first_expensive(self, strategy):
        """Спред > open_threshold → SELL left, BUY right."""
        left = _candle(Decimal("102"))
        right = _candle(Decimal("100"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_type == SignalType.SELL
        assert signal.right_type == SignalType.BUY

    def test_wait_when_spread_within_threshold(self, strategy):
        """|Спред| < open_threshold → WAIT."""
        left = _candle(Decimal("100"))
        right = _candle(Decimal("100.50"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_wait_at_exact_positive_boundary(self, strategy):
        """Спред ровно = open_threshold → WAIT (не строгое >)."""
        # Нужен спред ровно 1.0%: (first-second)/second*100 = 1.0
        # second=100, first=101 → spread = 1.0
        left = _candle(Decimal("101"))
        right = _candle(Decimal("100"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_type == SignalType.WAIT

    def test_wait_at_exact_negative_boundary(self, strategy):
        """Спред ровно = -open_threshold → WAIT."""
        # second=100, first=99 → spread = -1.0
        left = _candle(Decimal("99"))
        right = _candle(Decimal("100"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_type == SignalType.WAIT

    def test_signal_data_contains_spread(self, strategy):
        """signal.data содержит spread/price_first/price_second."""
        left = _candle(Decimal("100"))
        right = _candle(Decimal("102"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        data = SimpleArbitrageData(**signal.data)
        assert data.price_first == pytest.approx(100.0)
        assert data.price_second == pytest.approx(102.0)
        assert isinstance(data.spread, float)

    def test_zero_second_price_returns_wait(self, strategy):
        """Нулевая цена second → WAIT (error handling)."""
        left = _candle(Decimal("100"))
        right = _candle(Decimal("0"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_signal_prices_from_candles(self, strategy):
        """left_price/right_price из close свечей."""
        left = _candle(Decimal("98"))
        right = _candle(Decimal("100"), candle_id=2)
        trader = MagicMock()
        signal = strategy.get_signal(trader, left, right)
        assert signal.left_price == Decimal("98")
        assert signal.right_price == Decimal("100")


# ==================== position_should_be_closed ====================


class TestSimpleArbitrageStrategyPositionShouldBeClosed:
    """Тесты position_should_be_closed: проверка закрытия по спреду."""

    def _make_signal_with_spread(self, spread: float) -> ArbitrageTraderSignal:
        """Создаёт сигнал с заданным спредом в data."""
        candle = _candle(Decimal("100"))
        return ArbitrageTraderSignal(
            timestamp=candle.timestamp,
            left_price=Decimal("100"),
            right_price=Decimal("100"),
            left_type=SignalType.WAIT,
            right_type=SignalType.WAIT,
            left_candle=candle,
            data=SimpleArbitrageData(
                spread=spread, price_first=100.0, price_second=100.0
            ).model_dump(),
        )

    def _make_position(self, pos_type: PositionType) -> ArbitrageTraderPosition:
        """Создаёт позицию с заданным типом."""
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
            right_open_price=Decimal("102"),
        )

    def test_long_close_when_spread_recovered(self, strategy):
        """LONG: spread >= -close_threshold → True."""
        signal = self._make_signal_with_spread(-0.1)  # > -0.2 (close_threshold)
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_long_keep_when_spread_large(self, strategy):
        """LONG: spread < -close_threshold → False."""
        signal = self._make_signal_with_spread(-1.5)  # < -0.2
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_short_close_when_spread_recovered(self, strategy):
        """SHORT: spread <= close_threshold → True."""
        signal = self._make_signal_with_spread(0.1)  # < 0.2
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_short_keep_when_spread_large(self, strategy):
        """SHORT: spread > close_threshold → False."""
        signal = self._make_signal_with_spread(1.5)  # > 0.2
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_invalid_data_returns_false(self, strategy):
        """Невалидные data → False."""
        candle = _candle(Decimal("100"))
        signal = ArbitrageTraderSignal(
            timestamp=candle.timestamp,
            left_price=Decimal("100"),
            right_price=Decimal("100"),
            left_type=SignalType.WAIT,
            right_type=SignalType.WAIT,
            left_candle=candle,
            data={"invalid": "data"},
        )
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_boundary_long_at_close_threshold(self, strategy):
        """Граничное: spread = -close_threshold → True (>=)."""
        signal = self._make_signal_with_spread(-0.2)  # == -close_threshold
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True
