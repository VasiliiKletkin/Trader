"""
Общие фикстуры для всех доменных тестов.

Этот файл содержит базовые фикстуры, используемые в доменных тестах
всех приложений. Специфичные фикстуры находятся в conftest.py каждого домена.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from exchanges.domain import ExchangeCandle, MarketType, Timeframe, TradingPair

collect_ignore = [str(Path(__file__).parent / "test_ws.py")]


@pytest.fixture(autouse=True)
def _mock_send_notification():
    """Мокает send_notification в местах использования, чтобы избежать вызова asyncio.run."""
    with (
        patch("traders.models.traders.send_notification", new_callable=Mock),
        patch("arbitrage_traders.models.traders.send_notification", new_callable=Mock),
    ):
        yield


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
        base_currency="BTC",
        quote_currency="USDT",
        market_type=MarketType.FUTURES,
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        taker_fee=Decimal("0.001"),
        maker_fee=Decimal("0.001"),
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
