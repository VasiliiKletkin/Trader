"""
Тесты для Trader.
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from collections import deque

import pytest

from exchanges.domain.schemas import Candle, Timeframe, TradingPair
from exchange_clients.domain import (
    AbstractExchangeClient,
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from risk_managers.domain.base import AbstractRiskManager
from risk_managers.domain.schemas import (
    PositionType,
    PositionStatus,
    PositionCloseReason,
)
from strategies.domain.base import AbstractStrategy
from strategies.domain.schemas import SignalType, TraderSignal
from traders.domain.traders import Trader, TraderStatus
from traders.domain.schemas import TraderPosition


# ==================== Fixtures ====================


@pytest.fixture
def mock_trading_pair():
    """Mock торговой пары."""
    return TradingPair(
        name="BTC/USDT",
        symbol="BTCUSDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000.0"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def mock_timeframe():
    """Mock таймфрейма."""
    return Timeframe.ONE_HOUR


@pytest.fixture
def mock_exchange_client(mock_trading_pair):
    """Mock клиента биржи."""
    client = MagicMock()
    client.get_balance = Mock(return_value=Decimal("1000.00"))
    client.create_market_order = AsyncMock(
        return_value=ExchangeClientOrder(
            exchange_order_id="order_123",
            price=Decimal("100.00"),
            amount=Decimal("1.0"),
            fee=Decimal("0.1"),
            timestamp=datetime.now(timezone.utc),
            status=OrderStatus.CLOSED,
            trading_pair=mock_trading_pair,
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            cost=Decimal("100.00"),
        )
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_strategy():
    """Mock стратегии."""
    strategy = Mock(spec=AbstractStrategy)
    strategy.get_signal = Mock(
        return_value=TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("100.00"),
            data={},
        )
    )
    strategy.position_should_be_closed = Mock(return_value=False)
    return strategy


@pytest.fixture
def mock_risk_manager():
    """Mock риск-менеджера."""
    risk_manager = Mock(spec=AbstractRiskManager)
    risk_manager.calculate_position_size = Mock(return_value=Decimal("1.0"))
    risk_manager.get_stop_loss = Mock(return_value=Decimal("95.00"))
    risk_manager.get_take_profit = Mock(return_value=Decimal("110.00"))
    return risk_manager


@pytest.fixture
def sample_candle():
    """Тестовая свеча."""
    timestamp = datetime.now(timezone.utc)
    return Candle(
        ids=[1],
        dt_unix=int(timestamp.timestamp() * 1000),
        open=Decimal("100.00"),
        high=Decimal("110.00"),
        low=Decimal("90.00"),
        close=Decimal("105.00"),
        volume=Decimal("1000.00"),
    )


@pytest.fixture
def sample_candles():
    """Список тестовых свечей."""
    candles = []
    base_timestamp = datetime.now(timezone.utc)
    for i in range(10):
        candles.append(
            Candle(
                ids=[i],
                dt_unix=int(base_timestamp.timestamp() * 1000) + i * 60000,
                open=Decimal(str(100 + i)),
                high=Decimal(str(110 + i)),
                low=Decimal(str(90 + i)),
                close=Decimal(str(105 + i)),
                volume=Decimal(str(1000 + i * 100)),
            )
        )
    return candles


@pytest.fixture
def trader(
    mock_trading_pair,
    mock_timeframe,
    mock_exchange_client,
    mock_strategy,
    mock_risk_manager,
):
    """Инициализированный трейдер."""
    return Trader(
        trading_pair=mock_trading_pair,
        timeframe=mock_timeframe,
        exchange_client=mock_exchange_client,
        strategy=mock_strategy,
        risk_manager=mock_risk_manager,
        initial_balance=Decimal("1000.00"),
        balance=Decimal("1000.00"),
    )


@pytest.fixture
def opened_position():
    """Открытая позиция."""
    return TraderPosition(
        type=PositionType.LONG,
        status=PositionStatus.OPENED,
        open_price=Decimal("100.00"),
        amount=Decimal("1.0"),
        stop_loss=Decimal("95.00"),
        take_profit=Decimal("110.00"),
        opened_at=datetime.now(timezone.utc),
        recalculated_at=datetime.now(timezone.utc),
        total_fee=Decimal("0.1"),
    )


@pytest.fixture
def closed_position():
    """Закрытая позиция."""
    now = datetime.now(timezone.utc)
    return TraderPosition(
        type=PositionType.LONG,
        status=PositionStatus.CLOSED,
        open_price=Decimal("100.00"),
        close_price=Decimal("110.00"),
        amount=Decimal("1.0"),
        stop_loss=Decimal("95.00"),
        take_profit=Decimal("110.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        recalculated_at=now,
        total_fee=Decimal("0.2"),
        close_reason=PositionCloseReason.TAKE_PROFIT,
    )


# ==================== Initialization Tests ====================


class TestTraderInit:
    """Тесты инициализации Trader."""

    def test_init_default_values(
        self,
        mock_trading_pair,
        mock_timeframe,
        mock_exchange_client,
        mock_strategy,
        mock_risk_manager,
    ):
        """Тест инициализации с значениями по умолчанию."""
        trader = Trader(
            trading_pair=mock_trading_pair,
            timeframe=mock_timeframe,
            exchange_client=mock_exchange_client,
            strategy=mock_strategy,
            risk_manager=mock_risk_manager,
        )

        assert trader.trading_pair == mock_trading_pair
        assert trader.timeframe == mock_timeframe
        assert trader.exchange_client == mock_exchange_client
        assert trader.strategy == mock_strategy
        assert trader.risk_manager == mock_risk_manager
        assert trader.use_fixed_balance is True
        assert trader.initial_balance == Decimal("100.0")
        assert trader.balance == Decimal("100.0")
        assert trader.check_drawdown is True
        assert trader.max_drawdown_pct == Decimal("10.0")
        assert trader.max_positions_count == 1
        assert trader.trail_stop_enabled is True
        assert trader.create_new_orders is True
        assert trader.close_position_by_take_profit is True
        assert trader.close_position_by_stop_loss is True
        assert trader.close_position_by_strategy is True
        assert trader.close_position_by_opposite_signal is True
        assert trader.status == TraderStatus.ENABLED

    def test_init_custom_values(
        self,
        mock_trading_pair,
        mock_timeframe,
        mock_exchange_client,
        mock_strategy,
        mock_risk_manager,
    ):
        """Тест инициализации с пользовательскими значениями."""
        trader = Trader(
            trading_pair=mock_trading_pair,
            timeframe=mock_timeframe,
            exchange_client=mock_exchange_client,
            strategy=mock_strategy,
            risk_manager=mock_risk_manager,
            use_fixed_balance=False,
            initial_balance=Decimal("5000.00"),
            balance=Decimal("5000.00"),
            check_drawdown=False,
            max_drawdown_pct=Decimal("20.0"),
            max_positions_count=3,
            trail_stop_enabled=False,
            create_new_orders=False,
            close_position_by_take_profit=False,
            close_position_by_stop_loss=False,
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
        assert trader.trail_stop_enabled is False
        assert trader.create_new_orders is False
        assert trader.close_position_by_take_profit is False
        assert trader.close_position_by_stop_loss is False
        assert trader.close_position_by_strategy is False
        assert trader.close_position_by_opposite_signal is False
        assert trader.status == TraderStatus.DISABLED

    def test_init_empty_collections(self, trader):
        """Тест что коллекции пустые при инициализации."""
        assert isinstance(trader.candles, deque)
        assert len(trader.candles) == 0
        assert isinstance(trader.signals, deque)
        assert len(trader.signals) == 0
        assert isinstance(trader.orders, list)
        assert len(trader.orders) == 0
        assert isinstance(trader.positions, list)
        assert len(trader.positions) == 0
        assert isinstance(trader.positions_map, dict)
        assert len(trader.positions_map) == 0

    def test_init_errors_empty(self, trader):
        """Тест что ошибки пустые при инициализации."""
        assert trader.errors == ""
        assert trader.last_error is None


# ==================== Candles Tests ====================


class TestTraderCandles:
    """Тесты работы со свечами."""

    def test_add_candle(self, trader, sample_candle):
        """Тест добавления свечи."""
        trader.candles.append(sample_candle)

        assert len(trader.candles) == 1
        assert trader.candles[0] == sample_candle

    def test_get_last_candles_empty(self, trader):
        """Тест получения свечей из пустого списка."""
        candles = trader.get_last_candles(5)

        assert candles == []

    def test_get_last_candles_partial(self, trader, sample_candles):
        """Тест получения свечей когда их меньше запрошенного."""
        for candle in sample_candles[:3]:
            trader.candles.append(candle)

        candles = trader.get_last_candles(5)

        assert len(candles) == 3

    def test_get_last_candles_exact(self, trader, sample_candles):
        """Тест получения точного количества свечей."""
        for candle in sample_candles:
            trader.candles.append(candle)

        candles = trader.get_last_candles(5)

        assert len(candles) == 5

    def test_get_last_candles_returns_last(self, trader, sample_candles):
        """Тест что возвращаются последние свечи."""
        for candle in sample_candles:
            trader.candles.append(candle)

        candles = trader.get_last_candles(3)

        assert candles[-1] == sample_candles[-1]
        assert candles[-2] == sample_candles[-2]
        assert candles[-3] == sample_candles[-3]

    def test_candles_maxlen(self, trader):
        """Тест что deque имеет ограничение по размеру."""
        assert trader.candles.maxlen == 1000

    def test_get_last_candles_zero(self, trader, sample_candles):
        """Тест получения 0 свечей."""
        for candle in sample_candles:
            trader.candles.append(candle)

        candles = trader.get_last_candles(0)

        assert candles == []

    def test_get_last_candles_negative(self, trader, sample_candles):
        """Тест получения отрицательного количества свечей."""
        for candle in sample_candles:
            trader.candles.append(candle)

        candles = trader.get_last_candles(-5)

        assert candles == []

    def test_candles_order_preserved(self, trader, sample_candles):
        """Тест что порядок свечей сохраняется."""
        for candle in sample_candles:
            trader.candles.append(candle)

        for i, candle in enumerate(trader.candles):
            assert candle == sample_candles[i]


# ==================== Positions Tests ====================


class TestTraderPositions:
    """Тесты работы с позициями."""

    def test_opened_positions_empty(self, trader):
        """Тест получения открытых позиций из пустого списка."""
        opened = list(trader.opened_positions)

        assert opened == []

    def test_opened_positions_filters_correctly(
        self, trader, opened_position, closed_position
    ):
        """Тест фильтрации открытых позиций."""
        trader.positions = [opened_position, closed_position]

        opened = list(trader.opened_positions)

        assert len(opened) == 1
        assert opened[0] == opened_position

    def test_closed_positions_empty(self, trader):
        """Тест получения закрытых позиций из пустого списка."""
        closed = list(trader.closed_positions)

        assert closed == []

    def test_closed_positions_filters_correctly(
        self, trader, opened_position, closed_position
    ):
        """Тест фильтрации закрытых позиций."""
        trader.positions = [opened_position, closed_position]

        closed = list(trader.closed_positions)

        assert len(closed) == 1
        assert closed[0] == closed_position

    def test_count_opened_positions_zero(self, trader):
        """Тест подсчёта открытых позиций когда их нет."""
        count = len(list(trader.opened_positions))
        assert count == 0

    def test_count_opened_positions_multiple(self, trader):
        """Тест подсчёта нескольких открытых позиций."""
        for _ in range(3):
            position = TraderPosition(
                type=PositionType.LONG,
                status=PositionStatus.OPENED,
                open_price=Decimal("100.00"),
                amount=Decimal("1.0"),
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
                opened_at=datetime.now(timezone.utc),
                recalculated_at=datetime.now(timezone.utc),
                total_fee=Decimal("0.1"),
            )
            trader.positions.append(position)

        count = len(list(trader.opened_positions))
        assert count == 3

    def test_mixed_positions(self, trader):
        """Тест списка с разными статусами позиций."""
        now = datetime.now(timezone.utc)

        for i in range(5):
            status = PositionStatus.OPENED if i % 2 == 0 else PositionStatus.CLOSED
            position = TraderPosition(
                type=PositionType.LONG,
                status=status,
                open_price=Decimal("100.00"),
                close_price=(
                    Decimal("110.00") if status == PositionStatus.CLOSED else None
                ),
                amount=Decimal("1.0"),
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
                opened_at=now,
                closed_at=now if status == PositionStatus.CLOSED else None,
                recalculated_at=now,
                total_fee=Decimal("0.1"),
            )
            trader.positions.append(position)

        opened = list(trader.opened_positions)
        closed = list(trader.closed_positions)

        assert len(opened) == 3
        assert len(closed) == 2

    def test_positions_with_different_types(self, trader):
        """Тест позиций с разными типами (LONG/SHORT)."""
        now = datetime.now(timezone.utc)

        long_position = TraderPosition(
            type=PositionType.LONG,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
            opened_at=now,
            recalculated_at=now,
            total_fee=Decimal("0.1"),
        )

        short_position = TraderPosition(
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("105.00"),
            take_profit=Decimal("90.00"),
            opened_at=now,
            recalculated_at=now,
            total_fee=Decimal("0.1"),
        )

        trader.positions = [long_position, short_position]
        opened = list(trader.opened_positions)

        assert len(opened) == 2
        assert any(p.type == PositionType.LONG for p in opened)
        assert any(p.type == PositionType.SHORT for p in opened)


# ==================== Balance Tests ====================


class TestTraderBalance:
    """Тесты работы с балансом."""

    def test_initial_balance(self, trader):
        """Тест начального баланса."""
        assert trader.balance == Decimal("1000.00")
        assert trader.initial_balance == Decimal("1000.00")

    def test_get_current_balance_fixed(self, trader):
        """Тест получения текущего баланса при фиксированном балансе."""
        trader.use_fixed_balance = True
        trader.initial_balance = Decimal("1000.00")

        assert trader.get_current_balance() == Decimal("1000.00")

    def test_get_current_balance_not_fixed(self, trader, closed_position):
        """Тест получения текущего баланса при нефиксированном балансе."""
        trader.use_fixed_balance = False
        trader.balance = Decimal("1000.00")
        trader.positions = [closed_position]

        current = trader.get_current_balance()
        expected = Decimal("1000.00") + closed_position.pnl

        assert current == expected

    def test_get_current_balance_multiple_positions(self, trader):
        """Тест текущего баланса с несколькими закрытыми позициями."""
        trader.use_fixed_balance = False
        trader.balance = Decimal("1000.00")

        now = datetime.now(timezone.utc)
        positions = []

        for i in range(3):
            position = TraderPosition(
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("100.00"),
                close_price=Decimal(str(100 + (i + 1) * 5)),
                amount=Decimal("1.0"),
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
                opened_at=now - timedelta(hours=i + 1),
                closed_at=now,
                recalculated_at=now,
                total_fee=Decimal("0.1"),
            )
            positions.append(position)

        trader.positions = positions

        current = trader.get_current_balance()
        expected_pnl = sum(p.pnl for p in positions)

        assert current == Decimal("1000.00") + expected_pnl


# ==================== Drawdown Tests ====================


class TestTraderDrawdown:
    """Тесты проверки просадки."""

    def test_is_drawdown_within_limit_disabled(self, trader):
        """Тест что просадка не проверяется когда отключена."""
        trader.check_drawdown = False

        assert trader.is_drawdown_within_limit() is True

    def test_is_drawdown_within_limit_fixed_balance(self, trader):
        """Тест что просадка не проверяется при фиксированном балансе."""
        trader.check_drawdown = True
        trader.use_fixed_balance = True

        assert trader.is_drawdown_within_limit() is True

    def test_is_drawdown_within_limit_ok(self, trader):
        """Тест что просадка в пределах нормы."""
        trader.check_drawdown = True
        trader.use_fixed_balance = False
        trader.initial_balance = Decimal("1000.00")
        trader.balance = Decimal("950.00")  # 5% просадка
        trader.max_drawdown_pct = Decimal("10.0")

        assert trader.is_drawdown_within_limit() is True

    def test_is_drawdown_within_limit_exceeded(self, trader):
        """Тест что просадка превышена."""
        trader.check_drawdown = True
        trader.use_fixed_balance = False
        trader.initial_balance = Decimal("1000.00")
        trader.balance = Decimal("850.00")  # 15% просадка
        trader.max_drawdown_pct = Decimal("10.0")

        assert trader.is_drawdown_within_limit() is False

    def test_is_drawdown_within_limit_exact(self, trader):
        """Тест что просадка на границе допустима."""
        trader.check_drawdown = True
        trader.use_fixed_balance = False
        trader.initial_balance = Decimal("1000.00")
        trader.balance = Decimal("900.00")  # ровно 10% просадка
        trader.max_drawdown_pct = Decimal("10.0")

        assert trader.is_drawdown_within_limit() is True

    def test_is_drawdown_within_limit_zero_balance(self, trader):
        """Тест просадки при нулевом балансе."""
        trader.check_drawdown = True
        trader.use_fixed_balance = False
        trader.initial_balance = Decimal("1000.00")
        trader.balance = Decimal("0.00")
        trader.max_drawdown_pct = Decimal("10.0")

        assert trader.is_drawdown_within_limit() is False

    def test_is_drawdown_within_limit_profit(self, trader):
        """Тест что при прибыли просадка в норме."""
        trader.check_drawdown = True
        trader.use_fixed_balance = False
        trader.initial_balance = Decimal("1000.00")
        trader.balance = Decimal("1200.00")  # +20%
        trader.max_drawdown_pct = Decimal("10.0")

        assert trader.is_drawdown_within_limit() is True


# ==================== Can Open Position Tests ====================


class TestTraderCanOpenPosition:
    """Тесты проверки возможности открытия позиции."""

    def test_can_open_more_positions_true(self, trader):
        """Тест что можно открыть ещё позицию."""
        trader.max_positions_count = 2

        assert trader.can_open_more_positions() is True

    def test_can_open_more_positions_false(self, trader, opened_position):
        """Тест что нельзя открыть ещё позицию."""
        trader.max_positions_count = 1
        trader.positions = [opened_position]

        assert trader.can_open_more_positions() is False

    def test_can_open_position_wait_signal(self, trader):
        """Тест что нельзя открыть позицию при WAIT сигнале."""
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("100.00"),
            data={},
        )

        assert trader.can_open_position(signal, Decimal("100.00")) is False

    def test_can_open_position_buy_signal(self, trader):
        """Тест что можно открыть позицию при BUY сигнале."""
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        assert trader.can_open_position(signal, Decimal("100.00")) is True

    def test_can_open_position_sell_signal(self, trader):
        """Тест что можно открыть позицию при SELL сигнале."""
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.SELL,
            price=Decimal("100.00"),
            data={},
        )

        assert trader.can_open_position(signal, Decimal("100.00")) is True

    def test_can_open_position_max_positions_reached(self, trader, opened_position):
        """Тест что нельзя открыть позицию при достижении лимита."""
        trader.max_positions_count = 1
        trader.positions = [opened_position]

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        assert trader.can_open_position(signal, Decimal("100.00")) is False

    def test_can_open_position_drawdown_exceeded(self, trader):
        """Тест что нельзя открыть позицию при превышении просадки."""
        trader.check_drawdown = True
        trader.use_fixed_balance = False
        trader.initial_balance = Decimal("1000.00")
        trader.balance = Decimal("800.00")  # 20% просадка
        trader.max_drawdown_pct = Decimal("10.0")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        assert trader.can_open_position(signal, Decimal("100.00")) is False

    def test_can_open_more_positions_with_closed(
        self, trader, opened_position, closed_position
    ):
        """Тест что закрытые позиции не учитываются в лимите."""
        trader.max_positions_count = 1
        trader.positions = [opened_position, closed_position]

        assert trader.can_open_more_positions() is False

    def test_can_open_more_positions_only_closed(self, trader, closed_position):
        """Тест что можно открыть позицию если все закрыты."""
        trader.max_positions_count = 1
        trader.positions = [closed_position]

        assert trader.can_open_more_positions() is True


# ==================== Open Position Tests ====================


class TestTraderOpenPosition:
    """Тесты открытия позиции."""

    @pytest.mark.asyncio
    async def test_open_position_long(self, trader, mock_risk_manager):
        """Тест открытия LONG позиции."""
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )
        trader.create_new_orders = False

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is not None
        assert position.type == PositionType.LONG
        assert position.status == PositionStatus.OPENED
        assert len(trader.positions) == 1

    @pytest.mark.asyncio
    async def test_open_position_short(self, trader, mock_risk_manager):
        """Тест открытия SHORT позиции."""
        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.SELL,
            price=Decimal("100.00"),
            data={},
        )
        trader.create_new_orders = False

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is not None
        assert position.type == PositionType.SHORT
        assert position.status == PositionStatus.OPENED

    @pytest.mark.asyncio
    async def test_open_position_zero_amount(self, trader, mock_risk_manager):
        """Тест что позиция не открывается при нулевом amount."""
        mock_risk_manager.calculate_position_size.return_value = Decimal("0")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is None

    @pytest.mark.asyncio
    async def test_open_position_with_order(self, trader, mock_exchange_client):
        """Тест открытия позиции с созданием ордера."""
        trader.create_new_orders = True

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is not None
        mock_exchange_client.create_market_order.assert_called_once()
        assert len(trader.orders) == 1

    @pytest.mark.asyncio
    async def test_open_position_order_error(self, trader, mock_exchange_client):
        """Тест обработки ошибки при создании ордера."""
        trader.create_new_orders = True
        mock_exchange_client.create_market_order.side_effect = Exception("API Error")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is None
        assert "API Error" in trader.errors
        assert trader.last_error is not None

    @pytest.mark.asyncio
    async def test_open_position_sets_stop_loss(self, trader, mock_risk_manager):
        """Тест что при открытии устанавливается stop_loss."""
        mock_risk_manager.get_stop_loss.return_value = Decimal("95.00")
        trader.create_new_orders = False

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position.stop_loss == Decimal("95.00")

    @pytest.mark.asyncio
    async def test_open_position_sets_take_profit(self, trader, mock_risk_manager):
        """Тест что при открытии устанавливается take_profit."""
        mock_risk_manager.get_take_profit.return_value = Decimal("110.00")
        trader.create_new_orders = False

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position.take_profit == Decimal("110.00")


# ==================== Close Position Tests ====================


class TestTraderClosePosition:
    """Тесты закрытия позиции."""

    @pytest.mark.asyncio
    async def test_close_position_without_order(self, trader, opened_position):
        """Тест закрытия позиции без ордера."""
        trader.create_new_orders = False
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []

        closed = await trader.close_position(
            position=opened_position,
            price=Decimal("110.00"),
            timestamp=datetime.now(timezone.utc),
            reason=PositionCloseReason.TAKE_PROFIT,
        )

        assert closed is not None
        assert closed.status == PositionStatus.CLOSED
        assert closed.close_price == Decimal("110.00")
        assert closed.close_reason == PositionCloseReason.TAKE_PROFIT

    @pytest.mark.asyncio
    async def test_close_position_with_order(
        self, trader, opened_position, mock_exchange_client
    ):
        """Тест закрытия позиции с ордером."""
        trader.create_new_orders = True
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []

        closed = await trader.close_position(
            position=opened_position,
            price=Decimal("110.00"),
            timestamp=datetime.now(timezone.utc),
            reason=PositionCloseReason.TAKE_PROFIT,
        )

        assert closed is not None
        mock_exchange_client.create_market_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_position_order_error(
        self, trader, opened_position, mock_exchange_client
    ):
        """Тест обработки ошибки при закрытии позиции."""
        trader.create_new_orders = True
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []
        mock_exchange_client.create_market_order.side_effect = Exception("API Error")

        closed = await trader.close_position(
            position=opened_position,
            price=Decimal("110.00"),
            timestamp=datetime.now(timezone.utc),
            reason=PositionCloseReason.TAKE_PROFIT,
        )

        assert closed is None
        assert "API Error" in trader.errors

    @pytest.mark.asyncio
    async def test_close_position_sets_closed_at(self, trader, opened_position):
        """Тест что при закрытии устанавливается closed_at."""
        trader.create_new_orders = False
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []
        close_time = datetime.now(timezone.utc)

        closed = await trader.close_position(
            position=opened_position,
            price=Decimal("110.00"),
            timestamp=close_time,
            reason=PositionCloseReason.TAKE_PROFIT,
        )

        assert closed.closed_at == close_time

    @pytest.mark.asyncio
    async def test_close_position_all_reasons(self, trader, opened_position):
        """Тест закрытия позиции с разными причинами."""
        reasons = [
            PositionCloseReason.TAKE_PROFIT,
            PositionCloseReason.STOP_LOSS,
            PositionCloseReason.STRATEGY,
            PositionCloseReason.OPPOSITE_SIGNAL,
            PositionCloseReason.MANUAL,
        ]

        for reason in reasons:
            trader.create_new_orders = False
            position = TraderPosition(
                type=PositionType.LONG,
                status=PositionStatus.OPENED,
                open_price=Decimal("100.00"),
                amount=Decimal("1.0"),
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
                opened_at=datetime.now(timezone.utc),
                recalculated_at=datetime.now(timezone.utc),
                total_fee=Decimal("0.1"),
            )
            trader.positions = [position]
            trader.positions_map[id(position)] = []

            closed = await trader.close_position(
                position=position,
                price=Decimal("110.00"),
                timestamp=datetime.now(timezone.utc),
                reason=reason,
            )

            assert closed.close_reason == reason


# ==================== Update Position Tests ====================


class TestTraderUpdatePosition:
    """Тесты обновления позиции."""

    def test_update_position_long_better_stop_loss(
        self, trader, opened_position, mock_risk_manager
    ):
        """Тест обновления stop_loss для LONG позиции на лучшее значение."""
        opened_position.type = PositionType.LONG
        opened_position.stop_loss = Decimal("95.00")
        mock_risk_manager.get_stop_loss.return_value = Decimal("98.00")  # Лучше
        mock_risk_manager.get_take_profit.return_value = Decimal("110.00")

        trader.update_position(
            position=opened_position,
            price=Decimal("105.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert opened_position.stop_loss == Decimal("98.00")

    def test_update_position_long_worse_stop_loss(
        self, trader, opened_position, mock_risk_manager
    ):
        """Тест что stop_loss для LONG позиции не обновляется на худшее значение."""
        opened_position.type = PositionType.LONG
        opened_position.stop_loss = Decimal("95.00")
        mock_risk_manager.get_stop_loss.return_value = Decimal("90.00")  # Хуже
        mock_risk_manager.get_take_profit.return_value = Decimal("110.00")

        trader.update_position(
            position=opened_position,
            price=Decimal("105.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert opened_position.stop_loss == Decimal("95.00")

    def test_update_position_short_better_stop_loss(self, trader, mock_risk_manager):
        """Тест обновления stop_loss для SHORT позиции на лучшее значение."""
        position = TraderPosition(
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("105.00"),
            take_profit=Decimal("90.00"),
            opened_at=datetime.now(timezone.utc),
            recalculated_at=datetime.now(timezone.utc),
            total_fee=Decimal("0.1"),
        )
        mock_risk_manager.get_stop_loss.return_value = Decimal("102.00")  # Лучше
        mock_risk_manager.get_take_profit.return_value = Decimal("90.00")

        trader.update_position(
            position=position,
            price=Decimal("95.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position.stop_loss == Decimal("102.00")

    def test_update_position_short_worse_stop_loss(self, trader, mock_risk_manager):
        """Тест что stop_loss для SHORT позиции не обновляется на худшее значение."""
        position = TraderPosition(
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("105.00"),
            take_profit=Decimal("90.00"),
            opened_at=datetime.now(timezone.utc),
            recalculated_at=datetime.now(timezone.utc),
            total_fee=Decimal("0.1"),
        )
        mock_risk_manager.get_stop_loss.return_value = Decimal("110.00")  # Хуже
        mock_risk_manager.get_take_profit.return_value = Decimal("90.00")

        trader.update_position(
            position=position,
            price=Decimal("95.00"),
            timestamp=datetime.now(timezone.utc),
        )
        assert position.stop_loss == Decimal("105.00")

    def test_update_position_trail_stop_disabled(
        self, trader, opened_position, mock_risk_manager
    ):
        """Тест что stop_loss не обновляется при отключенном trail_stop."""
        opened_position.stop_loss = Decimal("95.00")
        mock_risk_manager.get_stop_loss.return_value = Decimal("98.00")
        mock_risk_manager.get_take_profit.return_value = Decimal("110.00")

        trader.update_position(
            position=opened_position,
            price=Decimal("105.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert opened_position.stop_loss == Decimal("98.00")

    def test_update_position_sets_recalculated_at(
        self, trader, opened_position, mock_risk_manager
    ):
        """Тест что при обновлении устанавливается recalculated_at."""
        mock_risk_manager.get_stop_loss.return_value = Decimal("98.00")
        mock_risk_manager.get_take_profit.return_value = Decimal("110.00")
        update_time = datetime.now(timezone.utc)

        trader.update_position(
            position=opened_position,
            price=Decimal("105.00"),
            timestamp=update_time,
        )

        assert opened_position.recalculated_at == update_time


# ==================== Position Should Be Closed Tests ====================


class TestTraderPositionShouldBeClosed:
    """Тесты проверки закрытия позиции."""

    def test_position_should_be_closed_by_stop_loss(self, trader, opened_position):
        """Тест закрытия по stop_loss."""
        trader.close_position_by_stop_loss = True
        opened_position.stop_loss = Decimal("95.00")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("94.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("94.00"),
        )

        assert should_close is True
        assert reason == PositionCloseReason.STOP_LOSS

    def test_position_should_be_closed_by_take_profit(self, trader, opened_position):
        """Тест закрытия по take_profit."""
        trader.close_position_by_take_profit = True
        opened_position.take_profit = Decimal("110.00")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("111.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("111.00"),
        )

        assert should_close is True
        assert reason == PositionCloseReason.TAKE_PROFIT

    def test_position_should_be_closed_by_strategy(
        self, trader, opened_position, mock_strategy
    ):
        """Тест закрытия по стратегии."""
        trader.close_position_by_strategy = True
        mock_strategy.position_should_be_closed.return_value = True

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("100.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("100.00"),
        )

        assert should_close is True
        assert reason == PositionCloseReason.STRATEGY

    def test_position_should_be_closed_by_opposite_signal_long(
        self, trader, opened_position
    ):
        """Тест закрытия LONG позиции при SELL сигнале."""
        trader.close_position_by_opposite_signal = True
        opened_position.type = PositionType.LONG

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.SELL,
            price=Decimal("100.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("100.00"),
        )

        assert should_close is True
        assert reason == PositionCloseReason.OPPOSITE_SIGNAL

    def test_position_should_be_closed_by_opposite_signal_short(self, trader):
        """Тест закрытия SHORT позиции при BUY сигнале."""
        trader.close_position_by_opposite_signal = True
        position = TraderPosition(
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("105.00"),
            take_profit=Decimal("90.00"),
            opened_at=datetime.now(timezone.utc),
            recalculated_at=datetime.now(timezone.utc),
            total_fee=Decimal("0.1"),
        )

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=position,
            signal=signal,
            price=Decimal("100.00"),
        )

        assert should_close is True
        assert reason == PositionCloseReason.OPPOSITE_SIGNAL

    def test_position_should_not_be_closed(
        self, trader, opened_position, mock_strategy
    ):
        """Тест что позиция не должна быть закрыта."""
        mock_strategy.position_should_be_closed.return_value = False

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("100.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("100.00"),
        )

        assert should_close is False
        assert reason is None

    def test_position_should_be_closed_stop_loss_disabled(
        self, trader, opened_position
    ):
        """Тест что stop_loss не срабатывает если отключен."""
        trader.close_position_by_stop_loss = False
        opened_position.stop_loss = Decimal("95.00")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("94.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("94.00"),
        )

        assert should_close is False

    def test_position_should_be_closed_take_profit_disabled(
        self, trader, opened_position
    ):
        """Тест что take_profit не срабатывает если отключен."""
        trader.close_position_by_take_profit = False
        opened_position.take_profit = Decimal("110.00")

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("111.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=opened_position,
            signal=signal,
            price=Decimal("111.00"),
        )

        assert should_close is False

    def test_position_should_be_closed_short_stop_loss(self, trader):
        """Тест закрытия SHORT позиции по stop_loss."""
        trader.close_position_by_stop_loss = True
        position = TraderPosition(
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("105.00"),
            take_profit=Decimal("90.00"),
            opened_at=datetime.now(timezone.utc),
            recalculated_at=datetime.now(timezone.utc),
            total_fee=Decimal("0.1"),
        )

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("106.00"),
            data={},
        )

        should_close, reason = trader.position_should_be_closed(
            position=position,
            signal=signal,
            price=Decimal("106.00"),
        )

        assert should_close is True
        assert reason == PositionCloseReason.STOP_LOSS


# ==================== Handle Candle Tests ====================


class TestTraderHandleCandle:
    """Тесты обработки свечей."""

    @pytest.mark.asyncio
    async def test_handle_candle_adds_candle_and_signal(self, trader, sample_candle):
        """Тест что handle_candle добавляет свечу и сигнал."""
        await trader.handle_candle(sample_candle)

        assert len(trader.candles) == 1
        assert len(trader.signals) == 1

    @pytest.mark.asyncio
    async def test_handle_candle_disabled_status(self, trader, sample_candle):
        """Тест что handle_candle не открывает позиции при DISABLED статусе."""
        trader.status = TraderStatus.DISABLED
        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        await trader.handle_candle(sample_candle)

        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_handle_candle_opens_position(self, trader, sample_candle):
        """Тест что handle_candle открывает позицию при сигнале."""
        trader.create_new_orders = False
        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        await trader.handle_candle(sample_candle)

        assert len(trader.positions) == 1

    @pytest.mark.asyncio
    async def test_handle_candle_closes_position_by_sl(
        self, trader, sample_candle, opened_position
    ):
        """Тест что handle_candle закрывает позицию по SL."""
        trader.create_new_orders = False
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []
        opened_position.stop_loss = Decimal("106.00")  # Выше текущей цены 105

        await trader.handle_candle(sample_candle)

        assert opened_position.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_handle_candle_exception_handling(
        self, trader, sample_candle, mock_strategy
    ):
        """Тест обработки исключения в handle_candle."""
        mock_strategy.get_signal.side_effect = Exception("Strategy error")

        await trader.handle_candle(sample_candle)

        assert "Strategy error" in trader.errors
        assert trader.last_error is not None

    @pytest.mark.asyncio
    async def test_handle_candle_multiple_candles(self, trader, sample_candles):
        """Тест обработки нескольких свечей."""
        for candle in sample_candles:
            await trader.handle_candle(candle)

        assert len(trader.candles) == len(sample_candles)
        assert len(trader.signals) == len(sample_candles)

    @pytest.mark.asyncio
    async def test_handle_candle_paused_status(self, trader, sample_candle):
        """Тест что handle_candle не открывает позиции при PAUSED статусе."""
        trader.status = TraderStatus.PAUSED
        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        await trader.handle_candle(sample_candle)

        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_handle_candle_updates_position(
        self, trader, sample_candle, opened_position, mock_risk_manager
    ):
        """Тест что handle_candle обновляет открытую позицию."""
        trader.create_new_orders = False
        trader.trail_stop_enabled = True
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []
        mock_risk_manager.get_stop_loss.return_value = Decimal("98.00")

        await trader.handle_candle(sample_candle)

        assert opened_position.stop_loss == Decimal("98.00")


# ==================== Check Opened Positions Tests ====================


class TestTraderCheckOpenedPositions:
    """Тесты проверки открытых позиций."""

    @pytest.mark.asyncio
    async def test_check_opened_positions_closes_by_sl(
        self, trader, sample_candle, opened_position
    ):
        """Тест что check_opened_positions закрывает позицию по SL."""
        trader.create_new_orders = False
        trader.positions = [opened_position]
        trader.positions_map[id(opened_position)] = []
        opened_position.stop_loss = Decimal("106.00")

        await trader.check_opened_positions(sample_candle)

        assert opened_position.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_check_opened_positions_disabled_status(
        self, trader, sample_candle, opened_position
    ):
        """Тест что check_opened_positions не работает при DISABLED статусе."""
        trader.status = TraderStatus.DISABLED
        trader.positions = [opened_position]

        await trader.check_opened_positions(sample_candle)

        assert opened_position.status == PositionStatus.OPENED

    @pytest.mark.asyncio
    async def test_check_opened_positions_exception_handling(
        self, trader, sample_candle, mock_strategy
    ):
        """Тест обработки исключения в check_opened_positions."""
        mock_strategy.get_signal.side_effect = Exception("Strategy error")

        await trader.check_opened_positions(sample_candle)

        assert "Strategy error" in trader.errors

    @pytest.mark.asyncio
    async def test_check_opened_positions_multiple(self, trader, sample_candle):
        """Тест проверки нескольких открытых позиций."""
        trader.create_new_orders = False
        positions = []

        for i in range(3):
            position = TraderPosition(
                type=PositionType.LONG,
                status=PositionStatus.OPENED,
                open_price=Decimal("100.00"),
                amount=Decimal("1.0"),
                stop_loss=Decimal("106.00"),  # Выше текущей цены
                take_profit=Decimal("110.00"),
                opened_at=datetime.now(timezone.utc),
                recalculated_at=datetime.now(timezone.utc),
                total_fee=Decimal("0.1"),
            )
            positions.append(position)
            trader.positions_map[id(position)] = []

        trader.positions = positions

        await trader.check_opened_positions(sample_candle)

        for position in positions:
            assert position.status == PositionStatus.CLOSED


# ==================== Close All Opened Positions Tests ====================


class TestTraderCloseAllOpenedPositions:
    """Тесты закрытия всех открытых позиций."""

    @pytest.mark.asyncio
    async def test_close_all_opened_positions(self, trader, opened_position):
        """Тест закрытия всех открытых позиций."""
        trader.create_new_orders = False
        position2 = TraderPosition(
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("100.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("105.00"),
            take_profit=Decimal("90.00"),
            opened_at=datetime.now(timezone.utc),
            recalculated_at=datetime.now(timezone.utc),
            total_fee=Decimal("0.1"),
        )
        trader.positions = [opened_position, position2]
        trader.positions_map[id(opened_position)] = []
        trader.positions_map[id(position2)] = []

        await trader.close_all_opened_positions()

        assert opened_position.status == PositionStatus.CLOSED
        assert position2.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_all_opened_positions_empty(self, trader):
        """Тест закрытия при отсутствии открытых позиций."""
        trader.positions = []

        await trader.close_all_opened_positions()

        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_close_all_opened_positions_skips_closed(
        self, trader, opened_position, closed_position
    ):
        """Тест что закрытые позиции не обрабатываются."""
        trader.create_new_orders = False
        trader.positions = [opened_position, closed_position]
        trader.positions_map[id(opened_position)] = []

        await trader.close_all_opened_positions()

        assert opened_position.status == PositionStatus.CLOSED
        assert closed_position.status == PositionStatus.CLOSED


# ==================== Reboot Tests ====================


class TestTraderReboot:
    """Тесты перезагрузки трейдера."""

    @pytest.mark.asyncio
    async def test_reboot(self, trader, sample_candles):
        """Тест перезагрузки трейдера."""
        trader.create_new_orders = True
        trader.strategy.get_signal.return_value = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        await trader.reboot(iter(sample_candles))

        # После reboot create_new_orders должен быть восстановлен
        assert trader.create_new_orders is True
        assert len(trader.candles) == len(sample_candles)


# ==================== Statistics Tests ====================


class TestTraderStatistics:
    """Тесты статистики трейдера."""

    def test_get_pnl_empty(self, trader):
        """Тест PnL без позиций."""
        assert trader.get_pnl() == Decimal("0")

    def test_get_pnl_with_positions(self, trader, closed_position):
        """Тест PnL с позициями."""
        trader.positions = [closed_position]

        pnl = trader.get_pnl()

        assert pnl == closed_position.pnl

    def test_get_roi(self, trader, closed_position):
        """Тест ROI."""
        trader.positions = [closed_position]
        trader.initial_balance = Decimal("1000.00")

        roi = trader.get_roi()

        expected = closed_position.pnl / Decimal("1000.00")
        assert roi == expected

    def test_get_win_rate_empty(self, trader):
        """Тест win rate без позиций."""
        assert trader.get_win_rate() == Decimal("0.0")

    def test_get_win_rate_with_positions(self, trader):
        """Тест win rate с позициями."""
        now = datetime.now(timezone.utc)

        winner = TraderPosition(
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("100.00"),
            close_price=Decimal("110.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
            opened_at=now - timedelta(hours=1),
            closed_at=now,
            recalculated_at=now,
            total_fee=Decimal("0.2"),
        )

        loser = TraderPosition(
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("100.00"),
            close_price=Decimal("90.00"),
            amount=Decimal("1.0"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
            opened_at=now - timedelta(hours=1),
            closed_at=now,
            recalculated_at=now,
            total_fee=Decimal("0.2"),
        )

        trader.positions = [winner, loser]

        win_rate = trader.get_win_rate()

        assert win_rate == Decimal("0.5")

    def test_get_pnl_r2_empty(self, trader):
        """Тест R² без позиций."""
        assert trader.get_pnl_r2() == Decimal("0.0")

    def test_get_pnl_r2_single_position(self, trader, closed_position):
        """Тест R² с одной позицией."""
        trader.positions = [closed_position]

        assert trader.get_pnl_r2() == Decimal("0.0")

    def test_get_sharpe_ratio_empty(self, trader):
        """Тест Sharpe ratio без позиций."""
        assert trader.get_sharpe_ratio() == Decimal("0.0")

    def test_get_total_positions(self, trader, opened_position, closed_position):
        """Тест общего количества позиций."""
        trader.positions = [opened_position, closed_position]

        assert trader.get_total_positions() == 2

    def test_get_avg_candles_per_position_empty(self, trader):
        """Тест среднего количества свечей без позиций."""
        assert trader.get_avg_candles_per_position() == Decimal("0.0")

    def test_get_avg_pnl_per_position_empty(self, trader):
        """Тест среднего PnL без позиций."""
        assert trader.get_avg_pnl_per_position() == Decimal("0.0")


# ==================== Market Order Tests ====================


class TestTraderCreateMarketOrder:
    """Тесты создания рыночных ордеров."""

    @pytest.mark.asyncio
    async def test_create_market_order(self, trader, mock_exchange_client):
        """Тест создания рыночного ордера."""
        order = await trader.create_market_order(
            side=OrderSide.BUY,
            amount=Decimal("1.0"),
        )

        assert order is not None
        mock_exchange_client.create_market_order.assert_called_once()
        assert len(trader.orders) == 1

    @pytest.mark.asyncio
    async def test_create_market_order_with_params(self, trader, mock_exchange_client):
        """Тест создания рыночного ордера с параметрами."""
        params = {"reduceOnly": True}

        await trader.create_market_order(
            side=OrderSide.SELL,
            amount=Decimal("1.0"),
            params=params,
        )

        mock_exchange_client.create_market_order.assert_called_once_with(
            trading_pair=trader.trading_pair,
            side=OrderSide.SELL,
            amount=Decimal("1.0"),
            params=params,
        )


# ==================== Status Tests ====================


class TestTraderStatus:
    """Тесты статуса трейдера."""

    def test_status_enabled(self, trader):
        """Тест статуса ENABLED."""
        trader.status = TraderStatus.ENABLED
        assert trader.status == TraderStatus.ENABLED

    def test_status_disabled(self, trader):
        """Тест статуса DISABLED."""
        trader.status = TraderStatus.DISABLED
        assert trader.status == TraderStatus.DISABLED

    def test_status_paused(self, trader):
        """Тест статуса PAUSED."""
        trader.status = TraderStatus.PAUSED
        assert trader.status == TraderStatus.PAUSED

    def test_status_rebooting(self, trader):
        """Тест статуса REBOOTING."""
        trader.status = TraderStatus.REBOOTING
        assert trader.status == TraderStatus.REBOOTING


# ==================== Get Signal Tests ====================


class TestTraderGetSignal:
    """Тесты получения сигнала."""

    def test_get_signal(self, trader, sample_candle, mock_strategy):
        """Тест получения сигнала от стратегии."""
        expected_signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )
        mock_strategy.get_signal.return_value = expected_signal

        signal = trader.get_signal(sample_candle)

        assert signal == expected_signal
        mock_strategy.get_signal.assert_called_once_with(
            trader=trader, candle=sample_candle
        )


# ==================== Edge Cases Tests ====================


class TestTraderEdgeCases:
    """Тесты граничных случаев."""

    def test_zero_balance(
        self,
        mock_trading_pair,
        mock_timeframe,
        mock_exchange_client,
        mock_strategy,
        mock_risk_manager,
    ):
        """Тест с нулевым балансом."""
        trader = Trader(
            trading_pair=mock_trading_pair,
            timeframe=mock_timeframe,
            exchange_client=mock_exchange_client,
            strategy=mock_strategy,
            risk_manager=mock_risk_manager,
            initial_balance=Decimal("0"),
            balance=Decimal("0"),
        )

        assert trader.balance == Decimal("0")
        assert trader.get_current_balance() == Decimal("0")

    def test_many_candles_respects_maxlen(self, trader, sample_candles):
        """Тест что deque ограничивает размер."""
        for _ in range(200):
            for candle in sample_candles:
                trader.candles.append(candle)

        assert len(trader.candles) <= trader.candles.maxlen

    def test_positions_map_operations(self, trader, opened_position):
        """Тест операций с картой позиций."""
        trader.positions_map[id(opened_position)] = ["order_1", "order_2"]

        assert len(trader.positions_map[id(opened_position)]) == 2

    @pytest.mark.asyncio
    async def test_open_position_min_amount(self, trader, mock_risk_manager):
        """Тест что amount корректируется до min_amount."""
        mock_risk_manager.calculate_position_size.return_value = Decimal("0.0001")
        trader.create_new_orders = False

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is not None
        assert position.amount >= trader.trading_pair.min_amount

    @pytest.mark.asyncio
    async def test_open_position_max_amount(self, trader, mock_risk_manager):
        """Тест что amount корректируется до max_amount."""
        mock_risk_manager.calculate_position_size.return_value = Decimal("10000.0")
        trader.create_new_orders = False

        signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("100.00"),
            data={},
        )

        position = await trader.open_position(
            signal=signal,
            price=Decimal("100.00"),
            timestamp=datetime.now(timezone.utc),
        )

        assert position is not None
        assert position.amount <= trader.trading_pair.max_amount
