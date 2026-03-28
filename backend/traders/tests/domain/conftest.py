"""
Фикстуры для доменных тестов traders app.

Объединяет фикстуры из:
- traders/domain/conftest.py (shared mocks)
- traders/domain/traders/tests/conftest.py (trader-specific)
- traders/domain/optimizations/tests/conftest.py (optimizer-specific)
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from exchanges.domain import ExchangeCandle, MarketType, Timeframe, TradingPair
from traders.domain.conftest import (  # noqa: F401
    downtrend_candles,
    mock_exchange_client,
    mock_position_long,
    mock_position_short,
    mock_risk_manager,
    mock_strategy,
    mock_trader,
    sample_candle,
    sample_candles,
)
from traders.domain.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
    TraderPosition,
)
from traders.domain.traders.traders import Trader

# ==================== Override ORM fixtures with pure-Python ====================


@pytest.fixture
def trading_pair() -> TradingPair:
    """Торговая пара без БД (переопределяет ORM-фикстуру из tests/conftest.py)."""
    return TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        type=MarketType.FUTURES,
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        taker_fee=Decimal("0.001"),
        maker_fee=Decimal("0.001"),
    )


@pytest.fixture
def timeframe() -> Timeframe:
    """Стандартный таймфрейм."""
    return Timeframe.ONE_HOUR


@pytest.fixture
def exchange_candle() -> ExchangeCandle:
    """Базовая свеча без БД."""
    timestamp = datetime.now(UTC)
    return ExchangeCandle(
        id=1,
        dt_unix=int(timestamp.timestamp() * 1000),
        open=Decimal("100.00"),
        high=Decimal("110.00"),
        low=Decimal("90.00"),
        close=Decimal("105.00"),
        volume=Decimal("1000.00"),
    )


# ==================== Trader-specific fixtures ====================


@pytest.fixture
def trader(
    trading_pair,
    timeframe,
    mock_exchange_client,  # noqa: F811
    mock_strategy,  # noqa: F811
    mock_risk_manager,  # noqa: F811
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


# ==================== Optimizer-specific fixtures ====================


@pytest.fixture
def simple_score_function():
    """Простая функция для оптимизации: максимизирует сумму."""

    def score(params: dict[str, Any]) -> Decimal:
        return Decimal(sum(params.values()))

    return score


@pytest.fixture
def quadratic_score_function():
    """Квадратичная функция с оптимумом в точке (5, 5)."""

    def score(params: dict[str, Any]) -> Decimal:
        x = params.get("x", 0)
        y = params.get("y", 0)
        return Decimal(50) - Decimal((x - 5) ** 2 + (y - 5) ** 2)

    return score


@pytest.fixture
def mock_candle_source():
    """Callable, возвращающий итератор из 100 тестовых свечей."""
    base_timestamp = datetime(2024, 1, 1, tzinfo=UTC)

    def get_candle_iterator():
        for i in range(100):
            timestamp = base_timestamp + timedelta(hours=i)
            yield ExchangeCandle(
                timestamp=timestamp,
                open=Decimal(50000 + i * 10),
                high=Decimal(50100 + i * 10),
                low=Decimal(49900 + i * 10),
                close=Decimal(50050 + i * 10),
                volume=Decimal(100),
            )

    return get_candle_iterator
