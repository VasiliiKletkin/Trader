"""
Shared fixtures for traders domain tests.
"""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock

import pytest

from candle_providers.domain import ProviderCandle
from exchange_clients.domain import (
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
from traders.domain.traders import Trader
from traders.domain.schemas import TraderPosition


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
            timestamp=datetime.now(timezone.utc),
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
def mock_strategy(provider_candle):
    """Mock стратегии."""
    strategy = Mock(spec=AbstractStrategy)
    strategy.get_signal = Mock(
        return_value=TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.WAIT,
            price=Decimal("100.00"),
            candle=provider_candle,
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


# ==================== Helper Functions ====================


def create_signal(
    candle: ProviderCandle, signal_type: SignalType = SignalType.WAIT
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
def sample_candle(provider_candle):
    """Алиас для provider_candle (для обратной совместимости)."""
    return provider_candle


def build_provider_candle(exchange_candle):
    """Wrap ExchangeCandle into ProviderCandle for testing."""
    return ProviderCandle(
        dt_unix=exchange_candle.dt_unix,
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
        primary_candle=exchange_candle,
        secondary_candle=None,
    )


@pytest.fixture
def sample_candles():
    """Список тестовых свечей для тестов трейдера."""
    from exchanges.domain import ExchangeCandle

    candles = []
    base_timestamp = datetime.now(timezone.utc)
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
        candles.append(build_provider_candle(exchange_candle))
    return candles
