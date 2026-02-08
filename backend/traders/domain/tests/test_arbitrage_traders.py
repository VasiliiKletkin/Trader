"""
Тесты для ArbitrageTrader.
"""

from collections import deque
from decimal import Decimal

import pytest

from risk_managers.domain.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
)
from strategies.domain.schemas import SignalType
from traders.domain.traders import ArbitrageTrader, TraderStatus

from .conftest import create_arbitrage_signal

# ==================== Initialization Tests ====================


class TestArbitrageTraderInit:
    """Тесты инициализации ArbitrageTrader."""

    def test_init_default_values(
        self,
        trading_pair,
        timeframe,
        mock_exchange_client,
        second_mock_exchange_client,
        mock_arbitrage_strategy,
        mock_arbitrage_risk_manager,
    ):
        """Тест инициализации с значениями по умолчанию."""
        trader = ArbitrageTrader(
            trading_pair=trading_pair,
            timeframe=timeframe,
            first_exchange_client=mock_exchange_client,
            second_exchange_client=second_mock_exchange_client,
            strategy=mock_arbitrage_strategy,
            risk_manager=mock_arbitrage_risk_manager,
        )

        assert trader.trading_pair == trading_pair
        assert trader.timeframe == timeframe
        assert trader.first_exchange_client == mock_exchange_client
        assert trader.second_exchange_client == second_mock_exchange_client
        assert trader.strategy == mock_arbitrage_strategy
        assert trader.risk_manager == mock_arbitrage_risk_manager
        assert trader.use_fixed_balance is True
        assert trader.initial_balance == Decimal("100.0")
        assert trader.balance == Decimal("100.0")
        assert trader.check_drawdown is True
        assert trader.max_drawdown_pct == Decimal("10.0")
        assert trader.max_positions_count == 1
        assert trader.create_new_orders is True
        assert trader.close_position_by_strategy is True
        assert trader.close_position_by_opposite_signal is True
        assert trader.status == TraderStatus.ENABLED

    def test_init_custom_values(
        self,
        trading_pair,
        timeframe,
        mock_exchange_client,
        second_mock_exchange_client,
        mock_arbitrage_strategy,
        mock_arbitrage_risk_manager,
    ):
        """Тест инициализации с пользовательскими значениями."""
        trader = ArbitrageTrader(
            trading_pair=trading_pair,
            timeframe=timeframe,
            first_exchange_client=mock_exchange_client,
            second_exchange_client=second_mock_exchange_client,
            strategy=mock_arbitrage_strategy,
            risk_manager=mock_arbitrage_risk_manager,
            use_fixed_balance=False,
            initial_balance=Decimal("5000.00"),
            balance=Decimal("5000.00"),
            check_drawdown=False,
            max_drawdown_pct=Decimal("20.0"),
            max_positions_count=3,
            create_new_orders=False,
            close_position_by_strategy=False,
            close_position_by_opposite_signal=False,
            status=TraderStatus.DISABLED,
        )

        assert trader.use_fixed_balance is False
        assert trader.initial_balance == Decimal("5000.00")
        assert trader.balance == Decimal("5000.00")
        assert trader.check_drawdown is False
        assert trader.max_drawdown_pct == Decimal("20.0")
        assert trader.max_positions_count == 3
        assert trader.create_new_orders is False
        assert trader.close_position_by_strategy is False
        assert trader.close_position_by_opposite_signal is False
        assert trader.status == TraderStatus.DISABLED

    def test_init_empty_collections(self, arbitrage_trader):
        """Тест что коллекции пустые при инициализации."""
        assert isinstance(arbitrage_trader.signals, deque)
        assert len(arbitrage_trader.signals) == 0
        assert isinstance(arbitrage_trader.positions, list)
        assert len(arbitrage_trader.positions) == 0
        assert isinstance(arbitrage_trader.errors, list)
        assert len(arbitrage_trader.errors) == 0


# ==================== Balance Tests ====================


class TestArbitrageTraderBalance:
    """Тесты баланса."""

    def test_get_current_balance_fixed(self, arbitrage_trader):
        """Тест получения фиксированного баланса."""
        arbitrage_trader.use_fixed_balance = True
        arbitrage_trader.balance = Decimal("500.00")
        assert arbitrage_trader.get_current_balance() == Decimal("500.00")

    def test_get_current_balance_not_fixed(
        self, arbitrage_trader, arbitrage_opened_position
    ):
        """Тест получения баланса с учетом открытых позиций."""
        arbitrage_trader.use_fixed_balance = False
        arbitrage_trader.balance = Decimal("1000.00")
        arbitrage_trader.positions.append(arbitrage_opened_position)
        # Открытая позиция не имеет pnl
        assert arbitrage_trader.get_current_balance() == Decimal("1000.00")


# ==================== Drawdown Tests ====================


class TestArbitrageTraderDrawdown:
    """Тесты проверки просадки."""

    def test_is_drawdown_within_limit_disabled(self, arbitrage_trader):
        """Тест когда проверка просадки отключена."""
        arbitrage_trader.check_drawdown = False
        arbitrage_trader.balance = Decimal("0.00")
        assert arbitrage_trader.is_drawdown_within_limit() is True

    def test_is_drawdown_within_limit_ok(self, arbitrage_trader):
        """Тест когда просадка в пределах лимита."""
        arbitrage_trader.check_drawdown = True
        arbitrage_trader.initial_balance = Decimal("1000.00")
        arbitrage_trader.balance = Decimal("950.00")
        arbitrage_trader.max_drawdown_pct = Decimal("10.0")
        assert arbitrage_trader.is_drawdown_within_limit() is True

    def test_is_drawdown_within_limit_exceeded(self, arbitrage_trader):
        """Тест когда просадка превышена."""
        arbitrage_trader.check_drawdown = True
        arbitrage_trader.initial_balance = Decimal("1000.00")
        arbitrage_trader.balance = Decimal("800.00")
        arbitrage_trader.max_drawdown_pct = Decimal("10.0")
        assert arbitrage_trader.is_drawdown_within_limit() is False


# ==================== Position Management Tests ====================


class TestArbitrageTraderPositions:
    """Тесты управления позициями."""

    def test_can_open_more_positions_empty(self, arbitrage_trader):
        """Тест когда нет открытых позиций."""
        assert arbitrage_trader.can_open_more_positions() is True

    def test_can_open_more_positions_limit_reached(
        self, arbitrage_trader, arbitrage_opened_position
    ):
        """Тест когда достигнут лимит позиций."""
        arbitrage_trader.max_positions_count = 1
        arbitrage_trader.positions.append(arbitrage_opened_position)
        assert arbitrage_trader.can_open_more_positions() is False

    def test_can_open_more_positions_under_limit(
        self, arbitrage_trader, arbitrage_opened_position
    ):
        """Тест когда лимит позиций не достигнут."""
        arbitrage_trader.max_positions_count = 2
        arbitrage_trader.positions.append(arbitrage_opened_position)
        assert arbitrage_trader.can_open_more_positions() is True

    def test_opened_positions_generator(
        self, arbitrage_trader, arbitrage_opened_position, arbitrage_closed_position
    ):
        """Тест генератора открытых позиций."""
        arbitrage_trader.positions.extend(
            [arbitrage_opened_position, arbitrage_closed_position]
        )
        opened = list(arbitrage_trader.opened_positions)
        assert len(opened) == 1
        assert opened[0].status == PositionStatus.OPENED

    def test_closed_positions_generator(
        self, arbitrage_trader, arbitrage_opened_position, arbitrage_closed_position
    ):
        """Тест генератора закрытых позиций."""
        arbitrage_trader.positions.extend(
            [arbitrage_opened_position, arbitrage_closed_position]
        )
        closed = list(arbitrage_trader.closed_positions)
        assert len(closed) == 1
        assert closed[0].status == PositionStatus.CLOSED


# ==================== Signal Tests ====================


class TestArbitrageTraderSignal:
    """Тесты генерации сигналов."""

    def test_get_signal(self, arbitrage_trader, provider_candle):
        """Тест генерации сигнала."""
        signal = arbitrage_trader.get_signal(provider_candle)
        assert signal is not None
        assert signal.first_type == SignalType.WAIT
        assert signal.second_type == SignalType.WAIT

    def test_can_open_position_wait_signals(self, arbitrage_trader, provider_candle):
        """Тест что нельзя открыть позицию при WAIT сигналах."""
        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.WAIT,
            second_type=SignalType.WAIT,
        )
        assert arbitrage_trader.can_open_position(signal) is False

    def test_can_open_position_buy_sell_signals(
        self, arbitrage_trader, provider_candle
    ):
        """Тест что можно открыть позицию при BUY/SELL сигналах."""
        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.BUY,
            second_type=SignalType.SELL,
        )
        assert arbitrage_trader.can_open_position(signal) is True

    def test_can_open_position_drawdown_exceeded(
        self, arbitrage_trader, provider_candle
    ):
        """Тест что нельзя открыть позицию при превышении просадки."""
        arbitrage_trader.check_drawdown = True
        arbitrage_trader.initial_balance = Decimal("1000.00")
        arbitrage_trader.balance = Decimal("800.00")
        arbitrage_trader.max_drawdown_pct = Decimal("10.0")

        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.BUY,
            second_type=SignalType.SELL,
        )
        assert arbitrage_trader.can_open_position(signal) is False


# ==================== Position Close Reason Tests ====================


class TestArbitrageTraderPositionShouldBeClosed:
    """Тесты проверки условий закрытия позиции."""

    def test_position_should_be_closed_strategy(
        self, arbitrage_trader, arbitrage_opened_position, provider_candle
    ):
        """Тест закрытия по условию стратегии."""
        arbitrage_trader.close_position_by_strategy = True
        arbitrage_trader.strategy.position_should_be_closed.return_value = True

        signal = create_arbitrage_signal(provider_candle)
        should_close, reason = arbitrage_trader.position_should_be_closed(
            arbitrage_opened_position, signal
        )

        assert should_close is True
        assert reason == PositionCloseReason.STRATEGY

    def test_position_should_be_closed_opposite_signal(
        self, arbitrage_trader, arbitrage_opened_position, provider_candle
    ):
        """Тест закрытия по противоположному сигналу."""
        arbitrage_trader.close_position_by_opposite_signal = True
        arbitrage_trader.strategy.position_should_be_closed.return_value = False
        arbitrage_opened_position.first_type = PositionType.LONG

        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.SELL,
            second_type=SignalType.BUY,
        )
        should_close, reason = arbitrage_trader.position_should_be_closed(
            arbitrage_opened_position, signal
        )

        assert should_close is True
        assert reason == PositionCloseReason.OPPOSITE_SIGNAL

    def test_position_should_not_be_closed(
        self, arbitrage_trader, arbitrage_opened_position, provider_candle
    ):
        """Тест когда позиция не должна быть закрыта."""
        arbitrage_trader.close_position_by_strategy = True
        arbitrage_trader.close_position_by_opposite_signal = True
        arbitrage_trader.strategy.position_should_be_closed.return_value = False

        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.WAIT,
            second_type=SignalType.WAIT,
        )
        should_close, reason = arbitrage_trader.position_should_be_closed(
            arbitrage_opened_position, signal
        )

        assert should_close is False
        assert reason is None


# ==================== Open Position Tests ====================


class TestArbitrageTraderOpenPosition:
    """Тесты открытия позиций."""

    @pytest.mark.asyncio
    async def test_open_position_creates_orders(
        self, arbitrage_trader, provider_candle
    ):
        """Тест что открытие позиции создает ордера на обеих биржах."""
        arbitrage_trader.create_new_orders = True
        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.BUY,
            second_type=SignalType.SELL,
        )

        position = await arbitrage_trader.open_position(signal)

        assert position is not None
        assert position.status == PositionStatus.OPENED
        assert position.first_type == PositionType.LONG
        assert position.second_type == PositionType.SHORT
        assert len(arbitrage_trader.positions) == 1
        arbitrage_trader.first_exchange_client.create_market_order.assert_called()
        arbitrage_trader.second_exchange_client.create_market_order.assert_called()

    @pytest.mark.asyncio
    async def test_open_position_without_orders(
        self, arbitrage_trader, provider_candle
    ):
        """Тест открытия позиции без реальных ордеров (симуляция)."""
        arbitrage_trader.create_new_orders = False
        signal = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.BUY,
            second_type=SignalType.SELL,
        )

        position = await arbitrage_trader.open_position(signal)

        assert position is not None
        assert position.status == PositionStatus.OPENED
        assert len(position.first_orders) == 0
        assert len(position.second_orders) == 0


# ==================== Close Position Tests ====================


class TestArbitrageTraderClosePosition:
    """Тесты закрытия позиций."""

    @pytest.mark.asyncio
    async def test_close_position(
        self, arbitrage_trader, arbitrage_opened_position, provider_candle
    ):
        """Тест закрытия позиции."""
        arbitrage_trader.create_new_orders = False
        arbitrage_trader.positions.append(arbitrage_opened_position)

        signal = create_arbitrage_signal(provider_candle)
        position = await arbitrage_trader.close_position(
            arbitrage_opened_position,
            signal,
            PositionCloseReason.STRATEGY,
        )

        assert position.status == PositionStatus.CLOSED
        assert position.close_reason == PositionCloseReason.STRATEGY
        assert position.first_close_price is not None
        assert position.second_close_price is not None

    @pytest.mark.asyncio
    async def test_close_all_opened_positions(
        self, arbitrage_trader, arbitrage_opened_position, provider_candle
    ):
        """Тест закрытия всех открытых позиций."""
        arbitrage_trader.create_new_orders = False
        arbitrage_trader.positions.append(arbitrage_opened_position)
        signal = create_arbitrage_signal(provider_candle)
        arbitrage_trader.signals.append(signal)

        await arbitrage_trader.close_all_opened_positions()

        assert all(
            pos.status == PositionStatus.CLOSED for pos in arbitrage_trader.positions
        )


# ==================== Handle Candle Tests ====================


class TestArbitrageTraderHandleCandle:
    """Тесты обработки свечей."""

    @pytest.mark.asyncio
    async def test_handle_candle_appends_signal(
        self, arbitrage_trader, provider_candle
    ):
        """Тест что handle_candle добавляет сигнал."""
        await arbitrage_trader.handle_candle(provider_candle)

        assert len(arbitrage_trader.signals) == 1

    @pytest.mark.asyncio
    async def test_handle_candle_disabled_status(
        self, arbitrage_trader, provider_candle
    ):
        """Тест что handle_candle не открывает позиции при DISABLED статусе."""
        arbitrage_trader.status = TraderStatus.DISABLED
        arbitrage_trader.strategy.get_signal.return_value = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.BUY,
            second_type=SignalType.SELL,
        )

        await arbitrage_trader.handle_candle(provider_candle)

        assert len(arbitrage_trader.positions) == 0

    @pytest.mark.asyncio
    async def test_handle_candle_opens_position(
        self, arbitrage_trader, provider_candle
    ):
        """Тест что handle_candle открывает позицию при сигнале."""
        arbitrage_trader.create_new_orders = False
        arbitrage_trader.strategy.get_signal.return_value = create_arbitrage_signal(
            provider_candle,
            first_type=SignalType.BUY,
            second_type=SignalType.SELL,
        )

        await arbitrage_trader.handle_candle(provider_candle)

        assert len(arbitrage_trader.positions) == 1

    @pytest.mark.asyncio
    async def test_handle_candle_exception_handling(
        self, arbitrage_trader, provider_candle
    ):
        """Тест обработки исключений."""
        arbitrage_trader.strategy.get_signal.side_effect = Exception("Test error")

        await arbitrage_trader.handle_candle(provider_candle)

        assert len(arbitrage_trader.errors) == 1
        assert "Test error" in arbitrage_trader.errors[0].message


# ==================== Statistics Tests ====================


class TestArbitrageTraderStatistics:
    """Тесты статистики."""

    def test_get_pnl_empty(self, arbitrage_trader):
        """Тест PnL без позиций."""
        assert arbitrage_trader.get_pnl() == 0

    def test_get_pnl_with_positions(self, arbitrage_trader, arbitrage_closed_position):
        """Тест PnL с закрытыми позициями."""
        arbitrage_trader.positions.append(arbitrage_closed_position)
        pnl = arbitrage_trader.get_pnl()
        # LONG first: (102 - 100) * 1 = 2
        # SHORT second: (100.5 - 99) * 1 = 1.5
        # Total: 2 + 1.5 - 0.4 (fee) = 3.1
        assert pnl == Decimal("3.1")

    def test_get_roi(self, arbitrage_trader, arbitrage_closed_position):
        """Тест ROI."""
        arbitrage_trader.initial_balance = Decimal("1000.00")
        arbitrage_trader.positions.append(arbitrage_closed_position)
        roi = arbitrage_trader.get_roi()
        # PnL = 3.1, ROI = 3.1 / 1000 * 100 = 0.31%
        assert roi == Decimal("0.31")

    def test_get_total_positions(
        self, arbitrage_trader, arbitrage_opened_position, arbitrage_closed_position
    ):
        """Тест общего количества позиций."""
        arbitrage_trader.positions.extend(
            [arbitrage_opened_position, arbitrage_closed_position]
        )
        assert arbitrage_trader.get_total_positions() == 2

    def test_get_avg_pnl_per_position_empty(self, arbitrage_trader):
        """Тест среднего PnL без позиций."""
        assert arbitrage_trader.get_avg_pnl_per_position() == Decimal("0.0")

    def test_get_avg_pnl_per_position(
        self, arbitrage_trader, arbitrage_closed_position
    ):
        """Тест среднего PnL с позициями."""
        arbitrage_trader.positions.append(arbitrage_closed_position)
        avg_pnl = arbitrage_trader.get_avg_pnl_per_position()
        assert avg_pnl == Decimal("3.1")


# ==================== Reboot Tests ====================


class TestArbitrageTraderReboot:
    """Тесты reboot."""

    @pytest.mark.asyncio
    async def test_reboot(self, arbitrage_trader, sample_candles):
        """Тест reboot на исторических свечах."""
        arbitrage_trader.create_new_orders = True

        await arbitrage_trader.reboot(iter(sample_candles))

        assert len(arbitrage_trader.signals) == len(sample_candles)
        assert arbitrage_trader.create_new_orders is True

    @pytest.mark.asyncio
    async def test_reboot_disables_orders_during_processing(
        self, arbitrage_trader, sample_candles
    ):
        """Тест что reboot отключает создание ордеров во время обработки."""
        arbitrage_trader.create_new_orders = True

        async def check_orders_disabled(candle):
            assert arbitrage_trader.create_new_orders is False

        original_handle = arbitrage_trader.handle_candle
        arbitrage_trader.handle_candle = check_orders_disabled

        await arbitrage_trader.reboot(iter(sample_candles[:1]))
        arbitrage_trader.handle_candle = original_handle

        assert arbitrage_trader.create_new_orders is True


# ==================== Candles Tests ====================


class TestArbitrageTraderCandles:
    """Тесты работы со свечами."""

    def test_get_last_candles_empty(self, arbitrage_trader):
        """Тест получения свечей из пустого списка."""
        candles = arbitrage_trader.get_last_candles(5)
        assert candles == []

    def test_get_last_candles(self, arbitrage_trader, sample_candles):
        """Тест получения последних свечей."""
        for candle in sample_candles:
            signal = create_arbitrage_signal(candle)
            arbitrage_trader.signals.append(signal)

        candles = arbitrage_trader.get_last_candles(5)
        assert len(candles) == 5

    def test_candles_generator(self, arbitrage_trader, sample_candles):
        """Тест генератора свечей."""
        for candle in sample_candles[:3]:
            signal = create_arbitrage_signal(candle)
            arbitrage_trader.signals.append(signal)

        candles = list(arbitrage_trader.candles)
        assert len(candles) == 3
