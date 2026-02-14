"""
Shared fixtures for traders domain tests.
"""

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from exchange_clients.domain import (
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from exchanges.domain import ExchangeCandle
from traders.domain.risk_managers.base import AbstractRiskManager
from traders.domain.schemas import (
    PositionStatus,
    PositionType,
    SignalType,
    TraderSignal,
)
from traders.domain.strategies.base import AbstractStrategy

# ==================== Helper Functions ====================


def make_test_candle(
    close: Decimal = Decimal("105"),
    dt_unix: int | None = None,
) -> ExchangeCandle:
    """Create a simple ExchangeCandle for testing."""
    if dt_unix is None:
        dt_unix = int(datetime.now(UTC).timestamp() * 1000)

    return ExchangeCandle(
        id=1,
        dt_unix=dt_unix,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=close,
        volume=Decimal("1000"),
    )


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


# ==================== Exchange Client ====================


@pytest.fixture
def mock_exchange_client(trading_pair):
    """Mock клиента биржи."""
    client = Mock()
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


# ==================== Mock Objects (for strategy/risk_manager tests) ====================


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
def mock_trader():
    """Mock трейдера."""
    trader = Mock()
    trader.candles = deque(maxlen=1000)
    trader.signals = deque(maxlen=1000)
    trader.get_last_candles = Mock(return_value=[])
    return trader


@pytest.fixture
def mock_position_long():
    """Mock LONG позиции."""
    position = Mock()
    position.type = PositionType.LONG
    position.status = PositionStatus.OPENED
    return position


@pytest.fixture
def mock_position_short():
    """Mock SHORT позиции."""
    position = Mock()
    position.type = PositionType.SHORT
    position.status = PositionStatus.OPENED
    return position


# ==================== Candles ====================


@pytest.fixture
def sample_candle(exchange_candle):
    """Алиас для exchange_candle (для обратной совместимости)."""
    return exchange_candle


@pytest.fixture
def sample_candles():
    """Список тестовых свечей для расчёта индикаторов."""
    candles = []
    base_timestamp = datetime.now(UTC)

    prices = [
        (100, 110, 95, 105, 1000),
        (105, 115, 100, 110, 1100),
        (110, 120, 105, 115, 1200),
        (115, 125, 110, 120, 1300),
        (120, 130, 115, 125, 1400),
        (125, 135, 120, 130, 1500),
        (130, 140, 125, 135, 1600),
        (135, 145, 130, 140, 1700),
        (140, 150, 135, 145, 1800),
        (145, 155, 140, 150, 1900),
        (150, 160, 145, 155, 2000),
        (155, 165, 150, 160, 2100),
        (160, 170, 155, 165, 2200),
        (165, 175, 160, 170, 2300),
        (170, 180, 165, 175, 2400),
    ]

    for i, (o, h, low_val, c, v) in enumerate(prices):
        timestamp_dt = base_timestamp + timedelta(hours=i)
        exchange_candle = ExchangeCandle(
            id=i,
            dt_unix=int(timestamp_dt.timestamp() * 1000),
            open=Decimal(str(o)),
            high=Decimal(str(h)),
            low=Decimal(str(low_val)),
            close=Decimal(str(c)),
            volume=Decimal(str(v)),
        )
        candles.append(exchange_candle)
    return candles


@pytest.fixture
def downtrend_candles():
    """Свечи с нисходящим трендом."""
    candles = []
    base_timestamp = datetime.now(UTC)

    prices = [
        (170, 180, 165, 175, 2400),
        (165, 175, 160, 170, 2300),
        (160, 170, 155, 165, 2200),
        (155, 165, 150, 160, 2100),
        (150, 160, 145, 155, 2000),
        (145, 155, 140, 150, 1900),
        (140, 150, 135, 145, 1800),
        (135, 145, 130, 140, 1700),
        (130, 140, 125, 135, 1600),
        (125, 135, 120, 130, 1500),
        (120, 130, 115, 125, 1400),
        (115, 125, 110, 120, 1300),
        (110, 120, 105, 115, 1200),
        (105, 115, 100, 110, 1100),
        (100, 110, 95, 105, 1000),
    ]

    for i, (o, h, low_val, c, v) in enumerate(prices):
        timestamp_dt = base_timestamp + timedelta(hours=i)
        exchange_candle = ExchangeCandle(
            id=i,
            dt_unix=int(timestamp_dt.timestamp() * 1000),
            open=Decimal(str(o)),
            high=Decimal(str(h)),
            low=Decimal(str(low_val)),
            close=Decimal(str(c)),
            volume=Decimal(str(v)),
        )
        candles.append(exchange_candle)
    return candles
