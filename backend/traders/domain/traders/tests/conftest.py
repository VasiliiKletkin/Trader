"""
Trader-specific test fixtures.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from exchanges.domain import ExchangeCandle
from traders.domain.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
    TraderPosition,
)
from traders.domain.traders.traders import Trader


@pytest.fixture
def sample_candles():
    """Список тестовых свечей для тестов трейдера (10 штук)."""
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
