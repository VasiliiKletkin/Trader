"""
Shared fixtures for traders domain tests.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from exchange_clients.domain import (
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from exchanges.domain import ExchangeCandle
from risk_managers.domain.base import AbstractArbitrageRiskManager, AbstractRiskManager
from risk_managers.domain.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
)
from strategies.domain.base import AbstractStrategy
from strategies.domain.schemas import ArbitrageTraderSignal, SignalType, TraderSignal
from traders.domain.schemas import ArbitrageTraderPosition, TraderPosition
from traders.domain.traders import ArbitrageTrader, Trader

# ==================== Exchange Client ====================


@pytest.fixture
def mock_exchange_client(trading_pair):
    """Mock клиента биржи."""
    client = MagicMock()
    client.get_balance = Mock(return_value=Decimal("1000.00"))
    client.create_market_order = AsyncMock(
        return_value=ExchangeClientOrder(
            exchange_order_id="order_123",
            price=Decimal("100.00"),
            amount=Decimal("1.0"),
            fee=Decimal("0.1"),
            timestamp=datetime.now(UTC),
            status=OrderStatus.CLOSED,
            trading_pair=trading_pair,
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            cost=Decimal("100.00"),
        )
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ==================== Strategy & Risk Manager ====================


@pytest.fixture
def mock_strategy(exchange_candle):
    """Mock стратегии."""
    strategy = Mock(spec=AbstractStrategy)
    strategy.get_signal = Mock(
        return_value=TraderSignal(
            timestamp=datetime.now(UTC),
            type=SignalType.WAIT,
            price=Decimal("100.00"),
            candle=exchange_candle,
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
def mock_arbitrage_risk_manager():
    """Mock арбитражного риск-менеджера."""
    risk_manager = Mock(spec=AbstractArbitrageRiskManager)
    risk_manager.calculate_position_size = Mock(return_value=Decimal("1.0"))
    return risk_manager


# ==================== Trader ====================


@pytest.fixture
def trader(
    trading_pair,
    timeframe,
    mock_exchange_client,
    mock_strategy,
    mock_risk_manager,
):
    """Инициализированный трейдер."""
    return Trader(
        trading_pair=trading_pair,
        timeframe=timeframe,
        exchange_client=mock_exchange_client,
        strategy=mock_strategy,
        risk_manager=mock_risk_manager,
        initial_balance=Decimal("1000.00"),
        balance=Decimal("1000.00"),
    )


# ==================== Positions ====================


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
        opened_at=datetime.now(UTC),
        recalculated_at=datetime.now(UTC),
        total_fee=Decimal("0.1"),
    )


@pytest.fixture
def closed_position():
    """Закрытая позиция."""
    now = datetime.now(UTC)
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


# ==================== Helper Functions ====================


def create_signal(
    candle: ExchangeCandle, signal_type: SignalType = SignalType.WAIT
) -> TraderSignal:
    """Создаёт TraderSignal с заданными параметрами."""
    return TraderSignal(
        timestamp=candle.timestamp,
        type=signal_type,
        price=candle.close,
        candle=candle,
        data={},
    )


@pytest.fixture
def sample_candle(exchange_candle):
    """Алиас для exchange_candle (для обратной совместимости)."""
    return exchange_candle


@pytest.fixture
def sample_candles():
    """Список тестовых свечей для тестов трейдера."""
    candles = []
    base_timestamp = datetime.now(UTC)
    for i in range(10):
        exchange_candle = ExchangeCandle(
            id=i,
            dt_unix=int(base_timestamp.timestamp() * 1000) + i * 60000,
            open=Decimal(str(100 + i)),
            high=Decimal(str(110 + i)),
            low=Decimal(str(90 + i)),
            close=Decimal(str(105 + i)),
            volume=Decimal(str(1000 + i * 100)),
        )
        candles.append(exchange_candle)
    return candles


# ==================== Arbitrage Trader ====================


@pytest.fixture
def second_mock_exchange_client(trading_pair):
    """Mock второго клиента биржи для арбитража."""
    client = MagicMock()
    client.get_balance = Mock(return_value=Decimal("1000.00"))
    client.create_market_order = AsyncMock(
        return_value=ExchangeClientOrder(
            exchange_order_id="order_456",
            price=Decimal("100.50"),
            amount=Decimal("1.0"),
            fee=Decimal("0.1"),
            timestamp=datetime.now(UTC),
            status=OrderStatus.CLOSED,
            trading_pair=trading_pair,
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            cost=Decimal("100.50"),
        )
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_arbitrage_strategy(exchange_candle):
    """Mock арбитражной стратегии."""
    strategy = Mock(spec=AbstractStrategy)
    strategy.get_signal = Mock(
        return_value=ArbitrageTraderSignal(
            timestamp=datetime.now(UTC),
            first_type=SignalType.WAIT,
            second_type=SignalType.WAIT,
            first_price=Decimal("100.00"),
            second_price=Decimal("100.50"),
            first_candle=exchange_candle,
            data={},
        )
    )
    strategy.position_should_be_closed = Mock(return_value=False)
    return strategy


@pytest.fixture
def arbitrage_trader(
    trading_pair,
    timeframe,
    mock_exchange_client,
    second_mock_exchange_client,
    mock_arbitrage_strategy,
    mock_arbitrage_risk_manager,
):
    """Инициализированный арбитражный трейдер."""
    return ArbitrageTrader(
        trading_pair=trading_pair,
        timeframe=timeframe,
        first_exchange_client=mock_exchange_client,
        second_exchange_client=second_mock_exchange_client,
        strategy=mock_arbitrage_strategy,
        risk_manager=mock_arbitrage_risk_manager,
        initial_balance=Decimal("1000.00"),
        balance=Decimal("1000.00"),
    )


@pytest.fixture
def arbitrage_opened_position():
    """Открытая арбитражная позиция."""
    return ArbitrageTraderPosition(
        type=PositionType.LONG,
        first_type=PositionType.LONG,
        second_type=PositionType.SHORT,
        status=PositionStatus.OPENED,
        amount=Decimal("1.0"),
        first_open_price=Decimal("100.00"),
        second_open_price=Decimal("100.50"),
        opened_at=datetime.now(UTC),
        total_fee=Decimal("0.2"),
    )


@pytest.fixture
def arbitrage_closed_position():
    """Закрытая арбитражная позиция."""
    now = datetime.now(UTC)
    return ArbitrageTraderPosition(
        type=PositionType.LONG,
        first_type=PositionType.LONG,
        second_type=PositionType.SHORT,
        status=PositionStatus.CLOSED,
        amount=Decimal("1.0"),
        first_open_price=Decimal("100.00"),
        first_close_price=Decimal("102.00"),
        second_open_price=Decimal("100.50"),
        second_close_price=Decimal("99.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        total_fee=Decimal("0.4"),
        close_reason=PositionCloseReason.STRATEGY,
    )


def create_arbitrage_signal(
    first_candle: ExchangeCandle,
    first_type: SignalType = SignalType.WAIT,
    second_type: SignalType = SignalType.WAIT,
    first_price: Decimal = Decimal("100.00"),
    second_price: Decimal = Decimal("100.50"),
    second_candle: ExchangeCandle | None = None,
) -> ArbitrageTraderSignal:
    """Создаёт ArbitrageTraderSignal с заданными параметрами."""
    return ArbitrageTraderSignal(
        timestamp=first_candle.timestamp,
        first_type=first_type,
        second_type=second_type,
        first_price=first_price,
        second_price=second_price,
        first_candle=first_candle,
        second_candle=second_candle,
        data={},
    )
