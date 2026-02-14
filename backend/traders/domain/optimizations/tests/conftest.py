"""
Optimizer-specific test fixtures.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest

from exchanges.domain import ExchangeCandle, Timeframe


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
def mock_candle_source(trading_pair):
    """Mock источника свечей."""
    source = Mock()

    source.trading_pair = trading_pair
    source.timeframe = Timeframe.ONE_HOUR

    def get_candle_iterator(start_date, end_date):
        """Генерирует 100 тестовых свечей."""
        base_timestamp = start_date
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

    source.get_candle_iterator = get_candle_iterator
    return source
