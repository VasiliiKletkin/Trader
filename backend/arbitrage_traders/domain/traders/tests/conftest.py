"""
Trader-specific fixtures for arbitrage trader domain tests.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from arbitrage_traders.domain.schemas import (
    ArbitrageTraderPosition,
    PositionCloseReason,
    PositionStatus,
    PositionType,
)
from arbitrage_traders.domain.traders import ArbitrageTrader
from exchanges.domain import ExchangeCandle

# ==================== Arbitrage Trader ====================


@pytest.fixture
def arbitrage_trader(
    trading_pair,
    timeframe,
    mock_exchange_client,
    right_mock_exchange_client,
    mock_arbitrage_strategy,
    mock_arbitrage_risk_manager,
):
    """Инициализированный арбитражный трейдер."""
    return ArbitrageTrader(
        trading_pair=trading_pair,
        timeframe=timeframe,
        left_exchange_client=mock_exchange_client,
        right_exchange_client=right_mock_exchange_client,
        strategy=mock_arbitrage_strategy,
        risk_manager=mock_arbitrage_risk_manager,
        initial_balance=Decimal("1000.00"),
        balance=Decimal("1000.00"),
    )


# ==================== Positions ====================


@pytest.fixture
def arbitrage_opened_position():
    """Открытая арбитражная позиция."""
    return ArbitrageTraderPosition(
        type=PositionType.LONG,
        left_type=PositionType.LONG,
        right_type=PositionType.SHORT,
        status=PositionStatus.OPENED,
        amount=Decimal("1.0"),
        left_open_price=Decimal("100.00"),
        right_open_price=Decimal("100.50"),
        opened_at=datetime.now(UTC),
        total_fee=Decimal("0.2"),
    )


@pytest.fixture
def arbitrage_closed_position():
    """Закрытая арбитражная позиция."""
    now = datetime.now(UTC)
    return ArbitrageTraderPosition(
        type=PositionType.LONG,
        left_type=PositionType.LONG,
        right_type=PositionType.SHORT,
        status=PositionStatus.CLOSED,
        amount=Decimal("1.0"),
        left_open_price=Decimal("100.00"),
        left_close_price=Decimal("102.00"),
        right_open_price=Decimal("100.50"),
        right_close_price=Decimal("99.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        total_fee=Decimal("0.4"),
        close_reason=PositionCloseReason.STRATEGY,
    )


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
