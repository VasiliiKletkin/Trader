"""
Тесты для доменной логики трейдера.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

from exchanges.domain.schemas import (
    Candle,
    Timeframe,
    TradingPair,
)
from exchange_clients.domain.schemas import (
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from risk_managers.domain import (
    AbstractRiskManager,
    PositionType,
    PositionStatus,
)
from traders.domain import TraderPosition
from strategies.domain import AbstractStrategy, SignalType, TraderSignal

from .traders import Trader


@pytest.fixture
def mock_trader():
    mock_exchange_client = Mock()

    def create_order_side_effect(**kwargs):
        side = kwargs.get("side", OrderSide.BUY)
        return ExchangeClientOrder(
            exchange_client=mock_exchange_client,
            status=OrderStatus.CLOSED,
            exchange_order_id="test_id",
            trading_pair=TradingPair(
                name="BTC/USDT", symbol="BTCUSDT", min_amount=Decimal("0.001")
            ),
            side=side,
            type=OrderType.MARKET,
            timestamp=datetime.now(timezone.utc),
            amount=kwargs.get("amount", Decimal("0.1")),
            price=Decimal("50000"),
            cost=Decimal("5000"),
            fee=Decimal("5"),
        )

    mock_exchange_client.create_market_order = AsyncMock(
        side_effect=create_order_side_effect
    )

    mock_strategy = Mock(spec=AbstractStrategy)
    mock_risk_manager = Mock(spec=AbstractRiskManager)

    trading_pair = TradingPair(
        name="BTC/USDT", symbol="BTCUSDT", min_amount=Decimal("0.001")
    )
    timeframe = Timeframe.ONE_MINUTE

    trader = Trader(
        trading_pair=trading_pair,
        timeframe=timeframe,
        exchange_client=mock_exchange_client,
        strategy=mock_strategy,
        risk_manager=mock_risk_manager,
        initial_balance=Decimal("1000"),
        max_drawdown_pct=Decimal("10"),
        max_positions_count=3,
        current_balance=Decimal("1000"),
        trail_stop_enabled=False,
        create_new_orders=True,
        close_position_by_take_profit=True,
        close_position_by_stop_loss=True,
        close_position_by_strategy=True,
        close_position_by_opposite_signal=True,
    )

    yield trader


class TestTrader:
    @pytest.mark.asyncio
    async def test_trader_initialization(self, mock_trader):
        trader = mock_trader
        assert trader.initial_balance == Decimal("1000")
        assert trader.current_balance == Decimal("1000")
        assert trader.max_drawdown_pct == Decimal("10")
        assert trader.max_positions_count == 3
        assert not trader.trail_stop_enabled
        assert len(trader.signals) == 0
        assert len(trader.candles) == 0
        assert len(trader.orders) == 0
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_create_market_order_buy(self, mock_trader):
        trader = mock_trader
        order = await trader.create_market_order(
            side=OrderSide.BUY,
            amount=Decimal("0.1"),
        )

        assert order.side == OrderSide.BUY
        assert order.amount == Decimal("0.1")
        assert order.price == Decimal("50000")
        assert order.status == OrderStatus.CLOSED
        assert len(trader.orders) == 1
        trader.exchange_client.create_market_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_market_order_sell(self, mock_trader):
        trader = mock_trader
        order = await trader.create_market_order(
            side=OrderSide.SELL,
            amount=Decimal("0.1"),
        )

        assert order.side == OrderSide.SELL
        assert order.amount == Decimal("0.1")
        assert order.price == Decimal("50000")
        assert len(trader.orders) == 1

    @pytest.mark.asyncio
    async def test_can_open_position_with_valid_signal(self, mock_trader):
        trader = mock_trader
        trader.check_drawdown_limit = AsyncMock(
            return_value=True
        )

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("50000"),
        )
        result = await trader.can_open_position(signal, Decimal("50000"))
        assert result is True

        signal_sell = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.SELL,
            price=Decimal("50000"),
        )
        result = await trader.can_open_position(signal_sell, Decimal("50000"))
        assert result is True

    @pytest.mark.asyncio
    async def test_can_open_position_with_invalid_signal(self, mock_trader):
        trader = mock_trader
        signal = TraderSignal(
            type=SignalType.WAIT,
            timestamp=datetime.now(timezone.utc),
            price=Decimal("50000"),
        )
        result = await trader.can_open_position(signal, Decimal("50000"))
        assert result is False

    @pytest.mark.asyncio
    async def test_can_open_position_with_drawdown_limit_exceeded(self, mock_trader):
        trader = mock_trader
        trader.check_drawdown_limit = AsyncMock(
            return_value=False
        )

        signal = TraderSignal(
            type=SignalType.BUY,
            timestamp=datetime.now(timezone.utc),
            price=Decimal("50000"),
        )
        result = await trader.can_open_position(signal, Decimal("50000"))
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_candle_integration(self, mock_trader):
        trader = mock_trader
        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("50000"),
        )

        trader.risk_manager.calculate_position_size.return_value = Decimal("0.1")
        trader.risk_manager.get_stop_loss.return_value = Decimal("45000")
        trader.risk_manager.get_take_profit.return_value = Decimal("55000")

        trader.check_drawdown_limit = AsyncMock(return_value=True)

        timestamp = datetime.now(timezone.utc)
        candle = Candle(
            timestamp=timestamp,
            dt_unix=int(timestamp.timestamp() * 1000),
            open=Decimal("49000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            close=Decimal("50000"),
            volume=Decimal("100"),
        )

        await trader.handle_candle(candle)

        trader.strategy.get_signal.assert_called_once()
        assert len(trader.candles) == 1
        assert trader.candles[0] == candle

    @pytest.mark.asyncio
    async def test_check_opened_positions_with_stop_loss(self, mock_trader):
        trader = mock_trader
        position = Mock(spec=TraderPosition)
        position.should_be_closed_by_stop_loss.return_value = True
        trader.positions = [position]

        timestamp = datetime.now(timezone.utc)
        candle = Candle(
            timestamp=timestamp,
            dt_unix=int(timestamp.timestamp() * 1000),
            open=Decimal("44000"),
            high=Decimal("44500"),
            low=Decimal("43000"),
            close=Decimal("44000"),
            volume=Decimal("100"),
        )

        await trader.check_opened_positions(candle)

        assert len(trader.orders) == 1
        assert trader.orders[0].side == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_maximum_positions_limit(self, mock_trader):
        trader = mock_trader
        for i in range(trader.max_positions_count):
            position = TraderPosition(
                type=PositionType.LONG,
                status=PositionStatus.OPENED,
                amount=Decimal("0.1"),
                open_price=Decimal("50000"),
                opened_at=datetime.now(timezone.utc),
            )
            trader.positions.append(position)

        trader.strategy.get_signal.return_value = SignalType.BUY
        trader.strategy.handle_candle = AsyncMock()

        trader.check_drawdown_limit = AsyncMock(
            return_value=True
        )

        timestamp = datetime.now(timezone.utc)
        candle = Candle(
            timestamp=timestamp,
            dt_unix=int(timestamp.timestamp() * 1000),
            open=Decimal("49000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            close=Decimal("50000"),
            volume=Decimal("100"),
        )

        initial_orders_count = len(trader.orders)

        await trader.handle_candle(candle)

        assert len(trader.orders) == initial_orders_count

    @pytest.mark.asyncio
    async def test_drawdown_limit_calculation(self, mock_trader):
        trader = mock_trader
        trader.current_balance = Decimal("850")

        result = await trader.check_drawdown_limit(
            trader.current_balance, trader.initial_balance
        )

        assert result is False

        trader.current_balance = Decimal("950")
        result = await trader.check_drawdown_limit(
            trader.current_balance, trader.initial_balance
        )

        assert result is True


class TestTraderIntegration:
    @pytest.fixture
    def integration_trader(self):
        mock_exchange_client = Mock()

        def create_order_side_effect(**kwargs):
            side = kwargs.get("side", OrderSide.BUY)
            return ExchangeClientOrder(
                exchange_client=mock_exchange_client,
                status=OrderStatus.CLOSED,
                exchange_order_id="test_id",
                trading_pair=TradingPair(
                    name="BTC/USDT", symbol="BTCUSDT", min_amount=Decimal("0.001")
                ),
                side=side,
                type=OrderType.MARKET,
                timestamp=datetime.now(timezone.utc),
                amount=kwargs.get("amount", Decimal("0.1")),
                price=Decimal("50000"),
                cost=Decimal("5000"),
                fee=Decimal("5"),
            )

        mock_exchange_client.create_market_order = AsyncMock(
            side_effect=create_order_side_effect
        )

        mock_strategy = Mock(spec=AbstractStrategy)
        mock_risk_manager = Mock(spec=AbstractRiskManager)

        trading_pair = TradingPair(
            name="BTC/USDT", symbol="BTCUSDT", min_amount=Decimal("0.001")
        )
        timeframe = Timeframe.ONE_MINUTE

        trader = Trader(
            trading_pair=trading_pair,
            timeframe=timeframe,
            exchange_client=mock_exchange_client,
            strategy=mock_strategy,
            risk_manager=mock_risk_manager,
            initial_balance=Decimal("1000"),
            max_drawdown_pct=Decimal("10"),
            max_positions_count=2,
            current_balance=Decimal("1000"),
            trail_stop_enabled=False,
            create_new_orders=True,
            close_position_by_take_profit=True,
            close_position_by_stop_loss=True,
            close_position_by_strategy=True,
            close_position_by_opposite_signal=True,
        )

        yield trader

    @pytest.mark.asyncio
    async def test_full_trading_cycle(self, integration_trader):
        trader = integration_trader
        trader.close_position_by_opposite_signal = False
        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("50000"),
        )

        trader.risk_manager.calculate_position_size.return_value = Decimal("0.1")
        trader.risk_manager.get_stop_loss.return_value = Decimal("45000")
        trader.risk_manager.get_take_profit.return_value = Decimal("55000")

        trader.check_drawdown_limit = AsyncMock(return_value=True)

        timestamp = datetime.now(timezone.utc)
        open_candle = Candle(
            timestamp=timestamp,
            dt_unix=int(timestamp.timestamp() * 1000),
            open=Decimal("49000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            close=Decimal("50000"),
            volume=Decimal("100"),
        )

        await trader.handle_candle(open_candle)

        assert len(trader.positions) == 1
        assert len(trader.orders) == 1
        assert trader.orders[0].side == OrderSide.BUY

        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.SELL,
            price=Decimal("55000"),
        )

        timestamp_close = datetime.now(timezone.utc)
        close_candle = Candle(
            timestamp=timestamp_close,
            dt_unix=int(timestamp_close.timestamp() * 1000),
            open=Decimal("55000"),
            high=Decimal("56000"),
            low=Decimal("54000"),
            close=Decimal("55000"),
            volume=Decimal("100"),
        )

        position = Mock(spec=TraderPosition)
        position.status = PositionStatus.OPENED
        position.type = PositionType.LONG
        position.should_be_closed_by_stop_loss.return_value = True
        trader.positions = [position]

        await trader.check_opened_positions(close_candle)

        sell_orders = [order for order in trader.orders if order.side == OrderSide.SELL]
        assert len(sell_orders) == 1

    @pytest.mark.asyncio
    async def test_multiple_signals_handling(self, integration_trader):
        trader = integration_trader
        signals = [SignalType.BUY, SignalType.WAIT, SignalType.SELL, SignalType.WAIT]
        expected_orders_count = 0

        trader.check_drawdown_limit = AsyncMock(return_value=True)

        trader.risk_manager.calculate_position_size.return_value = Decimal("0.1")
        trader.risk_manager.get_stop_loss.return_value = Decimal("45000")
        trader.risk_manager.get_take_profit.return_value = Decimal("55000")

        for i, signal in enumerate(signals):
            trader.strategy.get_signal.return_value = TraderSignal(
                timestamp=datetime.now(timezone.utc),
                type=signal,
                price=Decimal("50000"),
            )

            timestamp = datetime.now(timezone.utc)
            candle = Candle(
                timestamp=timestamp,
                dt_unix=int(timestamp.timestamp() * 1000),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50000"),
                volume=Decimal("100"),
            )

            await trader.handle_candle(candle)

            if signal in {SignalType.BUY, SignalType.SELL, SignalType.WAIT}:
                expected_orders_count += 1

            assert len(trader.signals) == i + 1

        assert len(trader.orders) == expected_orders_count
