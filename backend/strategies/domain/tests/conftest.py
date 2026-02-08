"""
Shared fixtures for strategies domain tests.
"""

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import pytest

from exchanges.domain import ExchangeCandle
from risk_managers.domain.schemas import PositionStatus, PositionType


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


# ==================== Mock Objects ====================


@pytest.fixture
def mock_trader():
    """Mock трейдера."""
    trader = MagicMock()
    trader.candles = deque(maxlen=1000)
    trader.signals = deque(maxlen=1000)
    trader.get_last_candles = Mock(return_value=[])
    return trader


@pytest.fixture
def mock_position_long():
    """Mock LONG позиции."""
    position = MagicMock()
    position.type = PositionType.LONG
    position.status = PositionStatus.OPENED
    return position


@pytest.fixture
def mock_position_short():
    """Mock SHORT позиции."""
    position = MagicMock()
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

    # Создаём свечи с разными ценами для тестирования индикаторов
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
