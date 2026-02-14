"""
Shared fixtures for arbitrage traders domain tests.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from arbitrage_traders.domain.risk_managers.base import AbstractArbitrageRiskManager
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderSignal,
    SignalType,
)
from arbitrage_traders.domain.strategies.base import AbstractArbitrageStrategy
from exchange_clients.domain import (
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from exchanges.domain import ExchangeCandle

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


@pytest.fixture
def right_mock_exchange_client(trading_pair):
    """Mock второго клиента биржи для арбитража."""
    client = Mock()
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


# ==================== Strategy & Risk Manager ====================


@pytest.fixture
def mock_arbitrage_strategy(exchange_candle):
    """Mock арбитражной стратегии."""
    strategy = Mock(spec=AbstractArbitrageStrategy)
    strategy.get_signal = Mock(
        return_value=ArbitrageTraderSignal(
            timestamp=datetime.now(UTC),
            left_type=SignalType.WAIT,
            right_type=SignalType.WAIT,
            left_price=Decimal("100.00"),
            right_price=Decimal("100.50"),
            left_candle=exchange_candle,
            data={},
        )
    )
    strategy.position_should_be_closed = Mock(return_value=False)
    return strategy


@pytest.fixture
def mock_arbitrage_risk_manager():
    """Mock арбитражного риск-менеджера."""
    risk_manager = Mock(spec=AbstractArbitrageRiskManager)
    risk_manager.calculate_position_size = Mock(return_value=Decimal("1.0"))
    return risk_manager


# ==================== Helper Functions ====================


def create_arbitrage_signal(
    left_candle: ExchangeCandle,
    left_type: SignalType = SignalType.WAIT,
    right_type: SignalType = SignalType.WAIT,
    left_price: Decimal = Decimal("100.00"),
    right_price: Decimal = Decimal("100.50"),
    right_candle: ExchangeCandle | None = None,
) -> ArbitrageTraderSignal:
    """Создаёт ArbitrageTraderSignal с заданными параметрами."""
    return ArbitrageTraderSignal(
        timestamp=left_candle.timestamp,
        left_type=left_type,
        right_type=right_type,
        left_price=left_price,
        right_price=right_price,
        left_candle=left_candle,
        right_candle=right_candle,
        data={},
    )
