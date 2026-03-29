"""
Тесты SpreadReversionArbitrageStrategy доменного слоя.
Фокус: валидация __init__, calculate_spread, get_signal, position_should_be_closed.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from arbitrage_traders.domain.schemas import (
    ArbitrageCandle,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    PositionStatus,
    PositionType,
    SignalType,
    SpreadReversionArbitrageData,
)
from arbitrage_traders.domain.strategies import (
    ArbitrageStrategyRegistry,
    SpreadReversionArbitrageStrategy,
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


class TestSpreadReversionArbitrageStrategyInit:
    """Тесты инициализации SpreadReversionArbitrageStrategy."""

    def test_default_values(self):
        """Дефолтные значения соответствуют константам класса."""
        s = SpreadReversionArbitrageStrategy()
        assert (
            s.open_threshold == SpreadReversionArbitrageStrategy.OPEN_THRESHOLD_DEFAULT
        )
        assert (
            s.close_threshold
            == SpreadReversionArbitrageStrategy.CLOSE_THRESHOLD_DEFAULT
        )

    def test_custom_values(self):
        """Кастомные значения сохраняются."""
        s = SpreadReversionArbitrageStrategy(open_threshold=0.03, close_threshold=0.015)
        assert s.open_threshold == 0.03
        assert s.close_threshold == 0.015

    def test_open_threshold_below_min_raises(self):
        """open_threshold < MIN → ValueError."""
        with pytest.raises(ValueError):
            SpreadReversionArbitrageStrategy(open_threshold=-0.01)

    def test_open_threshold_above_max_raises(self):
        """open_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            SpreadReversionArbitrageStrategy(open_threshold=0.2)

    def test_close_threshold_invalid_raises(self):
        """close_threshold > MAX → ValueError."""
        with pytest.raises(ValueError):
            SpreadReversionArbitrageStrategy(close_threshold=0.06)

    def test_non_numeric_type_raises(self):
        """Нечисловой тип → TypeError."""
        with pytest.raises(TypeError):
            SpreadReversionArbitrageStrategy(open_threshold="abc")

    def test_is_subclass_of_abstract(self):
        """Наследует AbstractArbitrageStrategy."""
        assert issubclass(SpreadReversionArbitrageStrategy, AbstractArbitrageStrategy)

    def test_registered_in_registry(self):
        """Зарегистрирован в ArbitrageStrategyRegistry."""
        cls = ArbitrageStrategyRegistry.get_class(
            SpreadReversionArbitrageStrategy.__name__
        )
        assert cls is SpreadReversionArbitrageStrategy


# ==================== spread (коэффициент left/right) ====================


class TestArbitrageCandleSpread:
    """Тесты ArbitrageCandle.spread: left / right."""

    def test_same_prices_parity(self):
        """Одинаковые цены → 1.0."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        assert candle.spread == 1.0

    def test_first_more_expensive_above_parity(self):
        """Первая дороже → spread > 1.0."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("98"), candle_id=2),
        )
        assert candle.spread == pytest.approx(1.0204, rel=0.01)

    def test_first_cheaper_below_parity(self):
        """Первая дешевле → spread < 1.0."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("98")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        assert candle.spread == pytest.approx(0.98, rel=0.01)

    def test_zero_second_price_raises(self):
        """Нулевая цена второй биржи → ValueError."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("0"), candle_id=2),
        )
        with pytest.raises(ValueError):
            _ = candle.spread

    def test_large_price_difference(self):
        """Большая разница цен → корректный коэффициент."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("200")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        assert candle.spread == pytest.approx(2.0, rel=0.01)


# ==================== get_signal ====================


class TestSpreadReversionArbitrageStrategyGetSignal:
    """Тесты get_signal: генерация торгового сигнала."""

    def test_buy_signal_when_first_cheaper(self, strategy):
        """spread < 1 - open_threshold → BUY left, SELL right."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("98")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_type == SignalType.BUY
        assert signal.right_type == SignalType.SELL

    def test_sell_signal_when_first_expensive(self, strategy):
        """spread > 1 + open_threshold → SELL left, BUY right."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("102")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_type == SignalType.SELL
        assert signal.right_type == SignalType.BUY

    def test_wait_when_spread_within_threshold(self, strategy):
        """1 - open_threshold <= spread <= 1 + open_threshold → WAIT."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("100.50"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_wait_at_exact_positive_boundary(self, strategy):
        """spread ровно = 1 + open_threshold → WAIT (не строгое >)."""
        # 101/100 = 1.01 == 1 + 0.01
        candle = ArbitrageCandle(
            left=_candle(Decimal("101")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_type == SignalType.WAIT

    def test_wait_at_exact_negative_boundary(self, strategy):
        """spread ровно = 1 - open_threshold → WAIT."""
        # 99/100 = 0.99 == 1 - 0.01
        candle = ArbitrageCandle(
            left=_candle(Decimal("99")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_type == SignalType.WAIT

    def test_signal_data_contains_spread(self, strategy):
        """signal.data содержит spread/left_price/right_price."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("102"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        data = SpreadReversionArbitrageData(**signal.data)
        assert data.left_price == pytest.approx(100.0)
        assert data.right_price == pytest.approx(102.0)
        assert isinstance(data.spread, float)

    def test_zero_second_price_returns_wait(self, strategy):
        """Нулевая цена second → WAIT (error handling)."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("100")),
            right=_candle(Decimal("0"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_type == SignalType.WAIT
        assert signal.right_type == SignalType.WAIT

    def test_signal_prices_from_candles(self, strategy):
        """left_price/right_price из close свечей."""
        candle = ArbitrageCandle(
            left=_candle(Decimal("98")),
            right=_candle(Decimal("100"), candle_id=2),
        )
        trader = MagicMock()
        signal = strategy.get_signal(trader, candle)
        assert signal.left_price == Decimal("98")
        assert signal.right_price == Decimal("100")


# ==================== position_should_be_closed ====================


class TestSpreadReversionArbitrageStrategyPositionShouldBeClosed:
    """Тесты position_should_be_closed: проверка закрытия по спреду."""

    def _make_signal_with_spread(self, spread: float) -> ArbitrageTraderSignal:
        """Создаёт сигнал с заданным спредом в data."""
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
            data=SpreadReversionArbitrageData(
                spread=spread, left_price=100.0, right_price=100.0
            ).model_dump(),
        )

    def _make_position(self, pos_type: PositionType) -> ArbitrageTraderPosition:
        """Создаёт позицию с заданным типом."""
        return ArbitrageTraderPosition(
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
        """LONG: spread >= 1 - close_threshold → True."""
        signal = self._make_signal_with_spread(0.999)  # > 1 - 0.002 = 0.998
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_long_keep_when_spread_large(self, strategy):
        """LONG: spread < 1 - close_threshold → False."""
        signal = self._make_signal_with_spread(0.985)  # < 0.998
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

    def test_short_close_when_spread_recovered(self, strategy):
        """SHORT: spread <= 1 + close_threshold → True."""
        signal = self._make_signal_with_spread(1.001)  # < 1 + 0.002 = 1.002
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True

    def test_short_keep_when_spread_large(self, strategy):
        """SHORT: spread > 1 + close_threshold → False."""
        signal = self._make_signal_with_spread(1.015)  # > 1.002
        pos = self._make_position(PositionType.SHORT)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is False

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

    def test_boundary_long_at_close_threshold(self, strategy):
        """Граничное: spread = 1 - close_threshold → True (>=)."""
        signal = self._make_signal_with_spread(0.998)  # == 1 - 0.002
        pos = self._make_position(PositionType.LONG)
        assert strategy.position_should_be_closed(signal=signal, position=pos) is True
