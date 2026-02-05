"""
Тесты для торговых стратегий.
"""

from collections import deque
from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pytest

from exchanges.domain import ExchangeCandle
from risk_managers.domain.schemas import PositionType, PositionStatus
from strategies.domain.base import AbstractStrategy
from strategies.domain.schemas import (
    SignalType,
    TraderSignal,
    RenkoBrick,
    RenkoData,
    MoneyFlowIndexStrategyData,
    StochasticData,
    DonchianCrossoverData,
)
from strategies.domain.strategies import (
    RenkoStrategy,
    MoneyFlowIndexStrategy,
    CounterMoneyFlowIndexStrategy,
    StochasticStrategy,
    CounterStochasticStrategy,
    DonchianCrossoverStrategy,
)
from .conftest import make_test_candle, build_provider_candle


# ==================== RenkoStrategy Tests ====================


class TestRenkoStrategy:
    """Тесты RenkoStrategy."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        strategy = RenkoStrategy()

        assert strategy.threshold_up == 1.0
        assert strategy.threshold_down == 1.0
        assert strategy.count_bricks == 3
        assert strategy.bricks == []

    def test_init_custom_values(self):
        """Тест инициализации с пользовательскими значениями."""
        strategy = RenkoStrategy(
            threshold_up=2.0,
            threshold_down=1.5,
            count_bricks=5,
        )

        assert strategy.threshold_up == 2.0
        assert strategy.threshold_down == 1.5
        assert strategy.count_bricks == 5

    def test_last_brick_empty(self):
        """Тест получения последнего кирпича из пустого списка."""
        strategy = RenkoStrategy()

        assert strategy.last_brick is None

    def test_last_brick_exists(self):
        """Тест получения последнего кирпича."""
        strategy = RenkoStrategy()
        brick = RenkoBrick(
            timestamp=datetime.now(timezone.utc),
            type="up",
            open=Decimal("100"),
            close=Decimal("101"),
        )
        strategy.bricks.append(brick)

        assert strategy.last_brick == brick

    def test_get_signal_first_candle(self, mock_trader, sample_candle):
        """Тест получения сигнала на первой свече."""
        strategy = RenkoStrategy()

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.type == SignalType.WAIT
        assert signal.price == sample_candle.close
        assert len(strategy.bricks) == 1
        assert strategy.bricks[0].type == "first"

    def test_get_signal_returns_new_bricks_in_data(self, mock_trader):
        """Тест что get_signal возвращает новые кирпичи в data."""
        strategy = RenkoStrategy(threshold_up=1.0, count_bricks=3)
        base_time = datetime.now(timezone.utc)

        candle1 = build_provider_candle(ExchangeCandle(
            id=1,
            dt_unix=int(base_time.timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ))
        signal = strategy.get_signal(mock_trader, candle1)

        # Проверяем что в data есть bricks
        assert "bricks" in signal.data

    def test_build_bricks_returns_up_bricks(self, mock_trader):
        """Тест что build_bricks возвращает кирпичи вверх."""
        strategy = RenkoStrategy(threshold_up=1.0, count_bricks=3)
        base_time = datetime.now(timezone.utc)

        # Первая свеча - создаём первый кирпич
        candle1 = build_provider_candle(ExchangeCandle(
            id=1,
            dt_unix=int(base_time.timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ))
        strategy.build_bricks(candle1, mock_trader)

        # Вторая свеча с ростом на 5%
        candle2 = build_provider_candle(ExchangeCandle(
            id=2,
            dt_unix=int((base_time + timedelta(hours=1)).timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("100"),
            close=Decimal("105"),
            volume=Decimal("1000"),
        ))
        new_bricks = strategy.build_bricks(candle2, mock_trader)

        # build_bricks возвращает новые кирпичи (не добавляет в self.bricks)
        assert len(new_bricks) > 0
        assert all(b.type == "up" for b in new_bricks)

    def test_build_bricks_returns_down_bricks(self, mock_trader):
        """Тест что build_bricks возвращает кирпичи вниз."""
        strategy = RenkoStrategy(threshold_down=1.0, count_bricks=3)
        base_time = datetime.now(timezone.utc)

        # Первая свеча
        candle1 = build_provider_candle(ExchangeCandle(
            id=1,
            dt_unix=int(base_time.timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ))
        strategy.build_bricks(candle1, mock_trader)

        # Вторая свеча с падением
        candle2 = build_provider_candle(ExchangeCandle(
            id=2,
            dt_unix=int((base_time + timedelta(hours=1)).timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("95"),
            close=Decimal("95"),
            volume=Decimal("1000"),
        ))
        new_bricks = strategy.build_bricks(candle2, mock_trader)

        # build_bricks возвращает новые кирпичи
        assert len(new_bricks) > 0
        assert all(b.type == "down" for b in new_bricks)

    def test_position_should_be_closed_always_false(self, mock_position_long):
        """Тест что position_should_be_closed всегда возвращает False."""
        strategy = RenkoStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.SELL,
            candle=candle,
            data={},
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_for_short(self, mock_position_short):
        """Тест что position_should_be_closed возвращает False для SHORT."""
        strategy = RenkoStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.BUY,
            candle=candle,
            data={},
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is False

    def test_create_bricks_up(self):
        """Тест создания кирпичей вверх."""
        strategy = RenkoStrategy()
        strategy.bricks.append(
            RenkoBrick(
                timestamp=datetime.now(timezone.utc),
                type="first",
                open=Decimal("100"),
                close=Decimal("100"),
            )
        )

        bricks = strategy.create_bricks(
            dt=datetime.now(timezone.utc),
            direction="up",
            count=3,
            brick_size=Decimal("1"),
        )

        assert len(bricks) == 3
        assert all(b.type == "up" for b in bricks)

    def test_create_bricks_down(self):
        """Тест создания кирпичей вниз."""
        strategy = RenkoStrategy()
        strategy.bricks.append(
            RenkoBrick(
                timestamp=datetime.now(timezone.utc),
                type="first",
                open=Decimal("100"),
                close=Decimal("100"),
            )
        )

        bricks = strategy.create_bricks(
            dt=datetime.now(timezone.utc),
            direction="down",
            count=2,
            brick_size=Decimal("1"),
        )

        assert len(bricks) == 2
        assert all(b.type == "down" for b in bricks)

    def test_create_bricks_with_wick(self):
        """Тест создания кирпичей с тенью."""
        strategy = RenkoStrategy()
        strategy.bricks.append(
            RenkoBrick(
                timestamp=datetime.now(timezone.utc),
                type="first",
                open=Decimal("100"),
                close=Decimal("100"),
            )
        )

        bricks = strategy.create_bricks(
            dt=datetime.now(timezone.utc),
            direction="up",
            count=2,
            brick_size=Decimal("1"),
            wick=Decimal("95"),
        )

        assert len(bricks) == 2
        assert bricks[0].low == Decimal("95")

    def test_update_wick_min(self):
        """Тест обновления минимальной тени."""
        strategy = RenkoStrategy()

        # Первый вызов с None
        result = strategy._update_wick_min(None, Decimal("100"))
        assert result == Decimal("100")

        # Обновление на меньшее значение
        result = strategy._update_wick_min(Decimal("100"), Decimal("95"))
        assert result == Decimal("95")

        # Не обновляется на большее значение
        result = strategy._update_wick_min(Decimal("95"), Decimal("100"))
        assert result == Decimal("95")

    def test_update_wick_max(self):
        """Тест обновления максимальной тени."""
        strategy = RenkoStrategy()

        # Первый вызов с None
        result = strategy._update_wick_max(None, Decimal("100"))
        assert result == Decimal("100")

        # Обновление на большее значение
        result = strategy._update_wick_max(Decimal("100"), Decimal("105"))
        assert result == Decimal("105")

        # Не обновляется на меньшее значение
        result = strategy._update_wick_max(Decimal("105"), Decimal("100"))
        assert result == Decimal("105")

    def test_param_constraints(self):
        """Тест ограничений параметров."""
        assert "threshold_up" in RenkoStrategy.PARAM_CONSTRAINTS
        assert "threshold_down" in RenkoStrategy.PARAM_CONSTRAINTS
        assert "count_bricks" in RenkoStrategy.PARAM_CONSTRAINTS

        assert RenkoStrategy.PARAM_CONSTRAINTS["threshold_up"] == (0.1, 10.0)
        assert RenkoStrategy.PARAM_CONSTRAINTS["count_bricks"] == (1, 10)

    def test_build_bricks_no_movement(self, mock_trader):
        """Тест что при отсутствии движения не создаются кирпичи."""
        strategy = RenkoStrategy(threshold_up=1.0, count_bricks=3)
        base_time = datetime.now(timezone.utc)

        # Первая свеча
        candle1 = build_provider_candle(ExchangeCandle(
            id=1,
            dt_unix=int(base_time.timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ))
        strategy.build_bricks(candle1, mock_trader)

        # Вторая свеча без значительного движения
        candle2 = build_provider_candle(ExchangeCandle(
            id=2,
            dt_unix=int((base_time + timedelta(hours=1)).timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("100.5"),
            low=Decimal("99.5"),
            close=Decimal("100.2"),
            volume=Decimal("1000"),
        ))
        new_bricks = strategy.build_bricks(candle2, mock_trader)

        # Движение меньше порога - новых кирпичей нет
        assert len(new_bricks) == 0

    def test_signal_contains_timestamp(self, mock_trader, sample_candle):
        """Тест что сигнал содержит timestamp свечи."""
        strategy = RenkoStrategy()

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.timestamp == sample_candle.timestamp


# ==================== MoneyFlowIndexStrategy Tests ====================


class TestMoneyFlowIndexStrategy:
    """Тесты MoneyFlowIndexStrategy."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        strategy = MoneyFlowIndexStrategy()

        assert strategy.period == 14
        assert strategy.overbought == 70.0
        assert strategy.oversold == 30.0
        assert strategy.median == 50.0

    def test_init_custom_values(self):
        """Тест инициализации с пользовательскими значениями."""
        strategy = MoneyFlowIndexStrategy(
            period=10,
            overbought=80.0,
            oversold=20.0,
            median=45.0,
        )

        assert strategy.period == 10
        assert strategy.overbought == 80.0
        assert strategy.oversold == 20.0
        assert strategy.median == 45.0

    def test_get_signal_insufficient_data(self, mock_trader, sample_candle):
        """Тест сигнала при недостаточных данных."""
        strategy = MoneyFlowIndexStrategy(period=14)
        mock_trader.get_last_candles.return_value = []

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.type == SignalType.WAIT

    def test_get_signal_with_enough_data(self, mock_trader, sample_candles):
        """Тест сигнала при достаточных данных."""
        strategy = MoneyFlowIndexStrategy(period=14)
        mock_trader.get_last_candles.return_value = sample_candles[:14]

        signal = strategy.get_signal(mock_trader, sample_candles[-1])

        assert signal.type in [SignalType.BUY, SignalType.SELL, SignalType.WAIT]
        assert "mfi_value" in signal.data

    def test_get_signal_buy_on_overbought(self, mock_trader, sample_candles):
        """Тест сигнала BUY при перекупленности."""
        strategy = MoneyFlowIndexStrategy(period=14, overbought=70.0)
        mock_trader.get_last_candles.return_value = sample_candles[:14]

        signal = strategy.get_signal(mock_trader, sample_candles[-1])

        # MFI при восходящем тренде будет высоким
        if signal.data.get("mfi_value", 0) > strategy.overbought:
            assert signal.type == SignalType.BUY

    def test_get_signal_sell_on_oversold(self, mock_trader, downtrend_candles):
        """Тест сигнала SELL при перепроданности."""
        strategy = MoneyFlowIndexStrategy(period=14, oversold=30.0)
        mock_trader.get_last_candles.return_value = downtrend_candles[:14]

        signal = strategy.get_signal(mock_trader, downtrend_candles[-1])

        if signal.data.get("mfi_value", 100) < strategy.oversold:
            assert signal.type == SignalType.SELL

    def test_position_should_be_closed_long_below_median(self, mock_position_long):
        """Тест закрытия LONG позиции когда MFI ниже медианы."""
        strategy = MoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is True

    def test_position_should_be_closed_long_above_median(self, mock_position_long):
        """Тест что LONG позиция не закрывается когда MFI выше медианы."""
        strategy = MoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_short_above_median(self, mock_position_short):
        """Тест закрытия SHORT позиции когда MFI выше медианы."""
        strategy = MoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is True

    def test_position_should_be_closed_short_below_median(self, mock_position_short):
        """Тест что SHORT позиция не закрывается когда MFI ниже медианы."""
        strategy = MoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is False

    def test_position_should_be_closed_invalid_data(self, mock_position_long):
        """Тест при невалидных данных сигнала."""
        strategy = MoneyFlowIndexStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data={"invalid": "data"},
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_empty_data(self, mock_position_long):
        """Тест при пустых данных сигнала."""
        strategy = MoneyFlowIndexStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data={},
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_at_median(self, mock_position_long):
        """Тест что позиция не закрывается когда MFI равен медиане."""
        strategy = MoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=50.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_param_constraints(self):
        """Тест ограничений параметров."""
        assert "period" in MoneyFlowIndexStrategy.PARAM_CONSTRAINTS
        assert "overbought" in MoneyFlowIndexStrategy.PARAM_CONSTRAINTS
        assert "oversold" in MoneyFlowIndexStrategy.PARAM_CONSTRAINTS

    def test_signal_price_equals_candle_close(self, mock_trader, sample_candle):
        """Тест что цена сигнала равна close свечи."""
        strategy = MoneyFlowIndexStrategy()
        mock_trader.get_last_candles.return_value = []

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.price == sample_candle.close


# ==================== CounterMoneyFlowIndexStrategy Tests ====================


class TestCounterMoneyFlowIndexStrategy:
    """Тесты CounterMoneyFlowIndexStrategy."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        strategy = CounterMoneyFlowIndexStrategy()

        assert strategy.period == 14
        assert strategy.overbought == 70.0
        assert strategy.oversold == 30.0
        assert strategy.median == 50.0

    def test_get_signal_buy_on_oversold(self, mock_trader, downtrend_candles):
        """Тест сигнала BUY при перепроданности (контртрендовая)."""
        strategy = CounterMoneyFlowIndexStrategy(period=14, oversold=30.0)
        mock_trader.get_last_candles.return_value = downtrend_candles[:14]

        signal = strategy.get_signal(mock_trader, downtrend_candles[-1])

        # В контртрендовой стратегии BUY при oversold
        if signal.data.get("mfi_value", 100) < strategy.oversold:
            assert signal.type == SignalType.BUY

    def test_get_signal_sell_on_overbought(self, mock_trader, sample_candles):
        """Тест сигнала SELL при перекупленности (контртрендовая)."""
        strategy = CounterMoneyFlowIndexStrategy(period=14, overbought=70.0)
        mock_trader.get_last_candles.return_value = sample_candles[:14]

        signal = strategy.get_signal(mock_trader, sample_candles[-1])

        # В контртрендовой стратегии SELL при overbought
        if signal.data.get("mfi_value", 0) > strategy.overbought:
            assert signal.type == SignalType.SELL

    def test_position_should_be_closed_long_above_median(self, mock_position_long):
        """Тест закрытия LONG позиции когда MFI выше медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is True

    def test_position_should_be_closed_long_below_median(self, mock_position_long):
        """Тест что LONG позиция не закрывается когда MFI ниже медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_short_below_median(self, mock_position_short):
        """Тест закрытия SHORT позиции когда MFI ниже медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is True

    def test_position_should_be_closed_short_above_median(self, mock_position_short):
        """Тест что SHORT позиция не закрывается когда MFI выше медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is False

    def test_param_constraints(self):
        """Тест ограничений параметров."""
        assert (
            CounterMoneyFlowIndexStrategy.PARAM_CONSTRAINTS
            == MoneyFlowIndexStrategy.PARAM_CONSTRAINTS
        )


# ==================== StochasticStrategy Tests ====================


class TestStochasticStrategy:
    """Тесты StochasticStrategy."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        strategy = StochasticStrategy()

        assert strategy.k_period == 14
        assert strategy.d_period == 3
        assert strategy.overbought == 80
        assert strategy.oversold == 20
        assert strategy.median == 50

    def test_init_custom_values(self):
        """Тест инициализации с пользовательскими значениями."""
        strategy = StochasticStrategy(
            k_period=10,
            d_period=5,
            overbought=75,
            oversold=25,
            median=55,
        )

        assert strategy.k_period == 10
        assert strategy.d_period == 5
        assert strategy.overbought == 75
        assert strategy.oversold == 25
        assert strategy.median == 55

    def test_init_invalid_k_period(self):
        """Тест ошибки при невалидном k_period."""
        with pytest.raises(ValueError, match="k_period должен быть в диапазоне"):
            StochasticStrategy(k_period=0)

        with pytest.raises(ValueError, match="k_period должен быть в диапазоне"):
            StochasticStrategy(k_period=5)  # Меньше минимума (10)

        with pytest.raises(ValueError, match="k_period должен быть в диапазоне"):
            StochasticStrategy(k_period=25)  # Больше максимума (20)

    def test_init_invalid_k_period_float(self):
        """Тест ошибки при дробном k_period."""
        with pytest.raises(TypeError, match="k_period должен быть целым числом"):
            StochasticStrategy(k_period=14.5)

    def test_init_invalid_d_period(self):
        """Тест ошибки при невалидном d_period."""
        with pytest.raises(ValueError, match="d_period должен быть в диапазоне"):
            StochasticStrategy(d_period=0)

    def test_init_invalid_d_period_negative(self):
        """Тест ошибки при отрицательном d_period."""
        with pytest.raises(ValueError, match="d_period должен быть в диапазоне"):
            StochasticStrategy(d_period=-3)

    def test_init_invalid_d_period_above_max(self):
        """Тест ошибки при d_period выше максимума."""
        with pytest.raises(ValueError, match="d_period должен быть в диапазоне"):
            StochasticStrategy(d_period=15)

    def test_init_invalid_oversold(self):
        """Тест ошибки при невалидном oversold."""
        with pytest.raises(ValueError, match="oversold должен быть в диапазоне"):
            StochasticStrategy(oversold=-10)

        with pytest.raises(ValueError, match="oversold должен быть в диапазоне"):
            StochasticStrategy(oversold=150)

    def test_init_invalid_overbought(self):
        """Тест ошибки при невалидном overbought."""
        with pytest.raises(ValueError, match="overbought должен быть в диапазоне"):
            StochasticStrategy(overbought=-10)

        with pytest.raises(ValueError, match="overbought должен быть в диапазоне"):
            StochasticStrategy(overbought=150)

    def test_init_invalid_median(self):
        """Тест ошибки при невалидном median."""
        with pytest.raises(ValueError, match="median должен быть в диапазоне"):
            StochasticStrategy(median=-10)

        with pytest.raises(ValueError, match="median должен быть в диапазоне"):
            StochasticStrategy(median=101)

    def test_init_boundary_values(self):
        """Тест граничных значений параметров."""
        # Используем допустимые граничные значения из PARAM_CONSTRAINTS
        strategy = StochasticStrategy(
            k_period=10,  # K_PERIOD_MIN
            d_period=1,  # D_PERIOD_MIN
            overbought=100,
            oversold=0,
            median=0,
        )
        assert strategy.k_period == 10
        assert strategy.d_period == 1
        assert strategy.overbought == 100
        assert strategy.oversold == 0

        # Тест максимальных значений
        strategy_max = StochasticStrategy(
            k_period=20,  # K_PERIOD_MAX
            d_period=10,  # D_PERIOD_MAX
            overbought=100,
            oversold=100,
            median=100,
        )
        assert strategy_max.k_period == 20
        assert strategy_max.d_period == 10

    def test_get_signal_insufficient_data(self, mock_trader, sample_candle):
        """Тест сигнала при недостаточных данных."""
        strategy = StochasticStrategy(k_period=14)
        mock_trader.get_last_candles.return_value = []

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.type == SignalType.WAIT

    def test_get_signal_with_enough_data(self, mock_trader, sample_candles):
        """Тест сигнала при достаточных данных."""
        strategy = StochasticStrategy(k_period=14, d_period=3)
        mock_trader.get_last_candles.return_value = sample_candles[:13]
        mock_trader.signals = deque()

        signal = strategy.get_signal(mock_trader, sample_candles[13])

        assert signal.type in [SignalType.BUY, SignalType.SELL, SignalType.WAIT]
        assert "k_value" in signal.data

    def test_get_signal_calculates_k_value(self, mock_trader, sample_candles):
        """Тест расчёта K value."""
        strategy = StochasticStrategy(k_period=14)
        mock_trader.get_last_candles.return_value = sample_candles[:13]
        mock_trader.signals = deque()

        signal = strategy.get_signal(mock_trader, sample_candles[13])

        k_value = signal.data.get("k_value")
        assert k_value is not None
        assert 0 <= k_value <= 100

    def test_get_signal_buy_on_overbought(self, mock_trader, sample_candles):
        """Тест сигнала BUY при перекупленности."""
        strategy = StochasticStrategy(k_period=14, d_period=3, overbought=80)
        mock_trader.get_last_candles.return_value = sample_candles[:13]

        # Создаём историю сигналов с высокими K values
        candle = make_test_candle()
        mock_trader.signals = deque(
            [
                TraderSignal(
                    timestamp=datetime.now(timezone.utc),
                    price=Decimal("100"),
                    type=SignalType.WAIT,
                    candle=candle,
                    data=StochasticData(k_value=85.0, d_value=None).model_dump(),
                )
                for _ in range(5)
            ]
        )

        signal = strategy.get_signal(mock_trader, sample_candles[13])

        d_value = signal.data.get("d_value")
        if d_value and d_value > strategy.overbought:
            assert signal.type == SignalType.BUY

    def test_get_signal_sell_on_oversold(self, mock_trader, downtrend_candles):
        """Тест сигнала SELL при перепроданности."""
        strategy = StochasticStrategy(k_period=14, d_period=3, oversold=20)
        mock_trader.get_last_candles.return_value = downtrend_candles[:13]

        # Создаём историю сигналов с низкими K values
        candle = make_test_candle()
        mock_trader.signals = deque(
            [
                TraderSignal(
                    timestamp=datetime.now(timezone.utc),
                    price=Decimal("100"),
                    type=SignalType.WAIT,
                    candle=candle,
                    data=StochasticData(k_value=15.0, d_value=None).model_dump(),
                )
                for _ in range(5)
            ]
        )

        signal = strategy.get_signal(mock_trader, downtrend_candles[13])

        d_value = signal.data.get("d_value")
        if d_value and d_value < strategy.oversold:
            assert signal.type == SignalType.SELL

    def test_position_should_be_closed_long_below_median(self, mock_position_long):
        """Тест закрытия LONG позиции когда D ниже медианы."""
        strategy = StochasticStrategy(median=50)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=StochasticData(k_value=40.0, d_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is True

    def test_position_should_be_closed_long_above_median(self, mock_position_long):
        """Тест что LONG позиция не закрывается когда D выше медианы."""
        strategy = StochasticStrategy(median=50)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=StochasticData(k_value=60.0, d_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_short_above_median(self, mock_position_short):
        """Тест закрытия SHORT позиции когда D выше медианы."""
        strategy = StochasticStrategy(median=50)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=StochasticData(k_value=60.0, d_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is True

    def test_position_should_be_closed_short_below_median(self, mock_position_short):
        """Тест что SHORT позиция не закрывается когда D ниже медианы."""
        strategy = StochasticStrategy(median=50)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=StochasticData(k_value=40.0, d_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is False

    def test_position_should_be_closed_invalid_data(self, mock_position_long):
        """Тест при невалидных данных сигнала."""
        strategy = StochasticStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data={"invalid": "data"},
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_none_d_value(self, mock_position_long):
        """Тест при None d_value."""
        strategy = StochasticStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data={"k_value": 40.0, "d_value": None},
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_param_constraints(self):
        """Тест ограничений параметров."""
        assert "k_period" in StochasticStrategy.PARAM_CONSTRAINTS
        assert "d_period" in StochasticStrategy.PARAM_CONSTRAINTS
        assert "overbought" in StochasticStrategy.PARAM_CONSTRAINTS
        assert "oversold" in StochasticStrategy.PARAM_CONSTRAINTS

        assert StochasticStrategy.PARAM_CONSTRAINTS["k_period"] == (10, 20)
        assert StochasticStrategy.PARAM_CONSTRAINTS["d_period"] == (1, 10)


# ==================== CounterStochasticStrategy Tests ====================


class TestCounterStochasticStrategy:
    """Тесты CounterStochasticStrategy."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        strategy = CounterStochasticStrategy()

        assert strategy.k_period == 14
        assert strategy.d_period == 3
        assert strategy.overbought == 80
        assert strategy.oversold == 20

    def test_get_signal_buy_on_oversold(self, mock_trader, downtrend_candles):
        """Тест сигнала BUY при выходе из зоны перепроданности (контртрендовая)."""
        strategy = CounterStochasticStrategy(k_period=14, d_period=3, oversold=20)
        mock_trader.get_last_candles.return_value = downtrend_candles[:13]

        candle = make_test_candle()
        # Предыдущий d_value должен быть < oversold (15 < 20)
        mock_trader.signals = deque(
            [
                TraderSignal(
                    timestamp=datetime.now(timezone.utc),
                    price=Decimal("100"),
                    type=SignalType.WAIT,
                    candle=candle,
                    data=StochasticData(k_value=15.0, d_value=15.0).model_dump(),
                )
                for _ in range(5)
            ]
        )

        signal = strategy.get_signal(mock_trader, downtrend_candles[13])

        d_value = signal.data.get("d_value")
        # BUY генерируется когда d_value пересекает oversold снизу вверх
        if d_value and d_value >= strategy.oversold:
            assert signal.type == SignalType.BUY

    def test_get_signal_sell_on_overbought(self, mock_trader, sample_candles):
        """Тест сигнала SELL при выходе из зоны перекупленности (контртрендовая)."""
        strategy = CounterStochasticStrategy(k_period=14, d_period=3, overbought=80)
        mock_trader.get_last_candles.return_value = sample_candles[:13]

        candle = make_test_candle()
        # Предыдущий d_value должен быть > overbought (85 > 80)
        mock_trader.signals = deque(
            [
                TraderSignal(
                    timestamp=datetime.now(timezone.utc),
                    price=Decimal("100"),
                    type=SignalType.WAIT,
                    candle=candle,
                    data=StochasticData(k_value=85.0, d_value=85.0).model_dump(),
                )
                for _ in range(5)
            ]
        )

        signal = strategy.get_signal(mock_trader, sample_candles[13])

        d_value = signal.data.get("d_value")
        # SELL генерируется когда d_value пересекает overbought сверху вниз
        if d_value and d_value <= strategy.overbought:
            assert signal.type == SignalType.SELL

    def test_position_should_be_closed_long_above_median(self, mock_position_long):
        """Тест закрытия LONG позиции когда MFI выше медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is True

    def test_position_should_be_closed_long_below_median(self, mock_position_long):
        """Тест что LONG позиция не закрывается когда MFI ниже медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_short_below_median(self, mock_position_short):
        """Тест закрытия SHORT позиции когда MFI ниже медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=40.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is True

    def test_position_should_be_closed_short_above_median(self, mock_position_short):
        """Тест что SHORT позиция не закрывается когда MFI выше медианы (контртренд)."""
        strategy = CounterMoneyFlowIndexStrategy(median=50.0)
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=MoneyFlowIndexStrategyData(mfi_value=60.0).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is False

    def test_param_constraints(self):
        """Тест ограничений параметров."""
        assert (
            CounterStochasticStrategy.PARAM_CONSTRAINTS
            == StochasticStrategy.PARAM_CONSTRAINTS
        )


# ==================== DonchianCrossoverStrategy Tests ====================


class TestDonchianCrossoverStrategy:
    """Тесты DonchianCrossoverStrategy."""

    def test_init_default_values(self):
        """Тест инициализации с значениями по умолчанию."""
        strategy = DonchianCrossoverStrategy()

        assert strategy.fast_period == 8
        assert strategy.slow_period == 12

    def test_init_custom_values(self):
        """Тест инициализации с пользовательскими значениями."""
        strategy = DonchianCrossoverStrategy(
            fast_period=10,
            slow_period=15,
        )

        assert strategy.fast_period == 10
        assert strategy.slow_period == 15

    def test_init_boundary_values(self):
        """Тест граничных значений параметров."""
        # Минимальные значения
        strategy_min = DonchianCrossoverStrategy(
            fast_period=5,  # FAST_PERIOD_MIN
            slow_period=10,  # SLOW_PERIOD_MIN
        )
        assert strategy_min.fast_period == 5
        assert strategy_min.slow_period == 10

        # Максимальные значения
        strategy_max = DonchianCrossoverStrategy(
            fast_period=15,  # FAST_PERIOD_MAX
            slow_period=20,  # SLOW_PERIOD_MAX
        )
        assert strategy_max.fast_period == 15
        assert strategy_max.slow_period == 20

    def test_init_invalid_fast_period(self):
        """Тест ошибки при невалидном fast_period."""
        with pytest.raises(ValueError, match="fast_period должен быть в диапазоне"):
            DonchianCrossoverStrategy(fast_period=3)

        with pytest.raises(ValueError, match="fast_period должен быть в диапазоне"):
            DonchianCrossoverStrategy(fast_period=20)

    def test_init_invalid_slow_period(self):
        """Тест ошибки при невалидном slow_period."""
        with pytest.raises(ValueError, match="slow_period должен быть в диапазоне"):
            DonchianCrossoverStrategy(slow_period=5)

        with pytest.raises(ValueError, match="slow_period должен быть в диапазоне"):
            DonchianCrossoverStrategy(slow_period=25)

    def test_get_signal_insufficient_data(self, mock_trader, sample_candle):
        """Тест сигнала при недостаточных данных."""
        strategy = DonchianCrossoverStrategy(fast_period=8, slow_period=12)
        mock_trader.get_last_candles.return_value = []

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.type == SignalType.WAIT

    def test_get_signal_with_enough_data(self, mock_trader, sample_candles):
        """Тест сигнала при достаточных данных."""
        strategy = DonchianCrossoverStrategy(fast_period=8, slow_period=12)
        mock_trader.get_last_candles.return_value = sample_candles[:11]

        signal = strategy.get_signal(mock_trader, sample_candles[11])

        assert signal.type in [SignalType.BUY, SignalType.SELL, SignalType.WAIT]
        assert "fast_upper" in signal.data
        assert "fast_lower" in signal.data
        assert "slow_upper" in signal.data
        assert "slow_lower" in signal.data

    def test_get_signal_calculates_channels(self, mock_trader, sample_candles):
        """Тест расчёта каналов Дончиана."""
        strategy = DonchianCrossoverStrategy(fast_period=5, slow_period=10)
        mock_trader.get_last_candles.return_value = sample_candles[:9]

        signal = strategy.get_signal(mock_trader, sample_candles[9])

        data = DonchianCrossoverData(**signal.data)

        assert data.fast_upper >= data.fast_lower
        assert data.slow_upper >= data.slow_lower

    def test_get_signal_wait_in_channel(self, mock_trader, sample_candles):
        """Тест сигнала WAIT когда цена внутри канала."""
        strategy = DonchianCrossoverStrategy(fast_period=5, slow_period=10)
        mock_trader.get_last_candles.return_value = sample_candles[:9]

        middle_candle = build_provider_candle(ExchangeCandle(
            id=100,
            dt_unix=int(datetime.now(timezone.utc).timestamp() * 1000),
            open=Decimal("120"),
            high=Decimal("125"),
            low=Decimal("115"),
            close=Decimal("120"),
            volume=Decimal("1000"),
        ))

        signal = strategy.get_signal(mock_trader, middle_candle)

        assert signal.type == SignalType.WAIT

    def test_param_constraints(self):
        """Тест ограничений параметров."""
        assert "fast_period" in DonchianCrossoverStrategy.PARAM_CONSTRAINTS
        assert "slow_period" in DonchianCrossoverStrategy.PARAM_CONSTRAINTS

        assert DonchianCrossoverStrategy.PARAM_CONSTRAINTS["fast_period"] == (5, 15)
        assert DonchianCrossoverStrategy.PARAM_CONSTRAINTS["slow_period"] == (10, 20)

    def test_channels_calculated_correctly(self, mock_trader):
        """Тест корректности расчёта каналов."""
        # Используем допустимые значения из PARAM_CONSTRAINTS
        strategy = DonchianCrossoverStrategy(fast_period=5, slow_period=10)
        base_time = datetime.now(timezone.utc)

        # Создаём свечи с известными значениями
        candles = [
            build_provider_candle(
                ExchangeCandle(
                    id=i,
                    dt_unix=int((base_time + timedelta(hours=i)).timestamp() * 1000),
                    open=Decimal("100"),
                    high=Decimal(str(100 + i * 10)),  # 100, 110, 120, 130, ...
                    low=Decimal(str(90 - i * 5)),  # 90, 85, 80, 75, ...
                    close=Decimal("100"),
                    volume=Decimal("1000"),
                )
            )
            for i in range(10)
        ]

        mock_trader.get_last_candles.return_value = candles[:9]

        signal = strategy.get_signal(mock_trader, candles[9])

        data = DonchianCrossoverData(**signal.data)

        # slow_upper = max high за 10 свечей = 190
        assert data.slow_upper == 190.0
        # slow_lower = min low за 10 свечей = 45
        assert data.slow_lower == 45.0

    def test_position_should_be_closed_long_below_fast_lower(self, mock_position_long):
        """Тест закрытия LONG позиции когда цена ниже fast_lower."""
        strategy = DonchianCrossoverStrategy()
        candle = make_test_candle(close=Decimal("80"))
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("80"),
            type=SignalType.WAIT,
            candle=candle,
            data=DonchianCrossoverData(
                fast_upper=110.0,
                fast_lower=90.0,
                slow_upper=120.0,
                slow_lower=80.0,
                candle_low=95.0,
                candle_high=105.0,
            ).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is True

    def test_position_should_be_closed_short_above_fast_upper(
        self, mock_position_short
    ):
        """Тест закрытия SHORT позиции когда цена выше fast_upper."""
        strategy = DonchianCrossoverStrategy()
        candle = make_test_candle(close=Decimal("115"))
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("115"),
            type=SignalType.WAIT,
            candle=candle,
            data=DonchianCrossoverData(
                fast_upper=110.0,
                fast_lower=90.0,
                slow_upper=120.0,
                slow_lower=80.0,
                candle_low=95.0,
                candle_high=105.0,
            ).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_short)

        assert result is True

    def test_position_should_be_closed_long_in_channel(self, mock_position_long):
        """Тест что LONG позиция не закрывается когда цена в канале."""
        strategy = DonchianCrossoverStrategy()
        candle = make_test_candle(close=Decimal("100"))
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data=DonchianCrossoverData(
                fast_upper=110.0,
                fast_lower=90.0,
                slow_upper=120.0,
                slow_lower=80.0,
                candle_low=95.0,
                candle_high=105.0,
            ).model_dump(),
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False

    def test_position_should_be_closed_invalid_data(self, mock_position_long):
        """Тест при невалидных данных сигнала."""
        strategy = DonchianCrossoverStrategy()
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100"),
            type=SignalType.WAIT,
            candle=candle,
            data={"invalid": "data"},
        )

        result = strategy.position_should_be_closed(signal, mock_position_long)

        assert result is False


# ==================== Schema Tests ====================


class TestTraderSignal:
    """Тесты схемы TraderSignal."""

    def test_create_signal(self):
        """Тест создания сигнала."""
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100.00"),
            type=SignalType.BUY,
            candle=candle,
            data={"key": "value"},
        )

        assert signal.type == SignalType.BUY
        assert signal.price == Decimal("100.00")
        assert signal.data == {"key": "value"}
        assert signal.id is None

    def test_signal_with_id(self):
        """Тест сигнала с ID."""
        candle = make_test_candle()
        signal = TraderSignal(
            id=123,
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100.00"),
            type=SignalType.SELL,
            candle=candle,
            data={},
        )

        assert signal.id == 123

    def test_signal_default_data(self):
        """Тест сигнала с пустыми данными по умолчанию."""
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("100.00"),
            type=SignalType.WAIT,
            candle=candle,
        )

        assert signal.data == {}

    def test_signal_contains_candle(self):
        """Тест что сигнал содержит свечу."""
        candle = make_test_candle(close=Decimal("150"))
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            price=Decimal("150.00"),
            type=SignalType.BUY,
            candle=candle,
            data={},
        )

        assert signal.candle == candle
        assert signal.candle.close == Decimal("150")

    def test_signal_timestamp_matches_candle(self):
        """Тест что timestamp сигнала соответствует свече."""
        candle = make_test_candle()
        signal = TraderSignal(
            timestamp=candle.timestamp,
            price=candle.close,
            type=SignalType.WAIT,
            candle=candle,
            data={},
        )

        assert signal.timestamp == candle.timestamp


class TestRenkoBrick:
    """Тесты схемы RenkoBrick."""

    def test_create_brick(self):
        """Тест создания кирпича."""
        brick = RenkoBrick(
            timestamp=datetime.now(timezone.utc),
            type="up",
            open=Decimal("100"),
            close=Decimal("101"),
        )

        assert brick.type == "up"
        assert brick.open == Decimal("100")
        assert brick.close == Decimal("101")

    def test_brick_with_wicks(self):
        """Тест кирпича с тенями."""
        brick = RenkoBrick(
            timestamp=datetime.now(timezone.utc),
            type="down",
            open=Decimal("100"),
            close=Decimal("99"),
            low=Decimal("98"),
            high=Decimal("101"),
        )

        assert brick.low == Decimal("98")
        assert brick.high == Decimal("101")


class TestSignalType:
    """Тесты enum SignalType."""

    def test_signal_types(self):
        """Тест типов сигналов."""
        assert SignalType.BUY.value == "buy"
        assert SignalType.SELL.value == "sell"
        assert SignalType.WAIT.value == "wait"


class TestStochasticData:
    """Тесты схемы StochasticData."""

    def test_create_data(self):
        """Тест создания данных."""
        data = StochasticData(k_value=50.0, d_value=45.0)

        assert data.k_value == 50.0
        assert data.d_value == 45.0

    def test_data_without_d_value(self):
        """Тест данных без D value."""
        data = StochasticData(k_value=50.0, d_value=None)

        assert data.k_value == 50.0
        assert data.d_value is None


class TestMoneyFlowIndexStrategyData:
    """Тесты схемы MoneyFlowIndexStrategyData."""

    def test_create_data(self):
        """Тест создания данных."""
        data = MoneyFlowIndexStrategyData(mfi_value=65.5)

        assert data.mfi_value == 65.5


class TestDonchianCrossoverData:
    """Тесты схемы DonchianCrossoverData."""

    def test_create_data(self):
        """Тест создания данных."""
        data = DonchianCrossoverData(
            fast_upper=110.0,
            fast_lower=90.0,
            slow_upper=120.0,
            slow_lower=80.0,
            candle_low=95.0,
            candle_high=105.0,
        )

        assert data.fast_upper == 110.0
        assert data.fast_lower == 90.0
        assert data.slow_upper == 120.0
        assert data.slow_lower == 80.0
        assert data.candle_low == 95.0
        assert data.candle_high == 105.0


# ==================== Edge Cases ====================


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_stochastic_same_high_low(self, mock_trader):
        """Тест стохастика когда high == low."""
        strategy = StochasticStrategy(k_period=14)

        # Создаём свечи с одинаковыми high и low
        candles = []
        base_time = datetime.now(timezone.utc)
        for i in range(14):
            candles.append(
                build_provider_candle(
                    ExchangeCandle(
                        id=i,
                        dt_unix=int(
                            (base_time + timedelta(hours=i)).timestamp() * 1000
                        ),
                        open=Decimal("100"),
                        high=Decimal("100"),
                        low=Decimal("100"),
                        close=Decimal("100"),
                        volume=Decimal("1000"),
                    )
                )
            )

        mock_trader.get_last_candles.return_value = candles[:13]
        mock_trader.signals = deque()

        signal = strategy.get_signal(mock_trader, candles[13])

        # Должен вернуть median при делении на ноль
        assert signal.data.get("k_value") == strategy.median

    def test_mfi_empty_signals_history(self, mock_trader, sample_candle):
        """Тест MFI с пустой историей сигналов."""
        strategy = MoneyFlowIndexStrategy(period=14)
        mock_trader.get_last_candles.return_value = []
        mock_trader.signals = deque()

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.type == SignalType.WAIT

    def test_donchian_single_candle(self, mock_trader, sample_candle):
        """Тест Донинен при одной свече."""
        strategy = DonchianCrossoverStrategy(fast_period=5, slow_period=10)
        mock_trader.get_last_candles.return_value = [sample_candle]

        signal = strategy.get_signal(mock_trader, sample_candle)

        assert signal.type == SignalType.WAIT
