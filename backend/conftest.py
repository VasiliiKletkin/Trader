"""
Общие фикстуры для всех доменных тестов.

Этот файл содержит базовые фикстуры, используемые в доменных тестах
всех приложений. Специфичные фикстуры находятся в conftest.py каждого домена.
"""

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from exchanges.domain import ExchangeCandle, Timeframe, TradingPair
from candle_providers.domain import ProviderCandle


# ==================== Trading Pair & Timeframe ====================


@pytest.fixture
def trading_pair() -> TradingPair:
    """
    Стандартная торговая пара BTC/USDT для всех тестов.

    ВАЖНО: Используется единый формат symbol="BTC/USDT:USDT"
    для консистентности во всех доменах.
    """
    return TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def timeframe() -> Timeframe:
    """Стандартный таймфрейм 1 час для всех тестов."""
    return Timeframe.ONE_HOUR


# ==================== Candles ====================


@pytest.fixture
def exchange_candle() -> ExchangeCandle:
    """
    Базовая ExchangeCandle для тестов.

    Создает свечу с текущим timestamp и стандартными OHLCV значениями.
    """
    timestamp = datetime.now(timezone.utc)
    return ExchangeCandle(
        id=1,
        dt_unix=int(timestamp.timestamp() * 1000),
        open=Decimal("100.00"),
        high=Decimal("110.00"),
        low=Decimal("90.00"),
        close=Decimal("105.00"),
        volume=Decimal("1000.00"),
    )


@pytest.fixture
def provider_candle(exchange_candle) -> ProviderCandle:
    """
    ProviderCandle построенная из exchange_candle.

    Используется для тестов, где нужна обертка провайдера
    (трейдеры, стратегии, оптимизаторы).
    """
    return ProviderCandle(
        dt_unix=exchange_candle.dt_unix,
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
        first_candle=exchange_candle,
        second_candle=None,
    )
