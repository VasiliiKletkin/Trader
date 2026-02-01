"""
Test helpers for creating test objects.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from candle_providers.domain import ProviderCandle
from candle_sources.domain.shemas import Candle as SourceCandle
from exchanges.domain import ExchangeCandle


def build_candle(dt_unix: int) -> SourceCandle:
    """Create a simple SourceCandle for testing."""
    return SourceCandle(
        dt_unix=dt_unix,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1000"),
    )


def build_provider_candle(
    exchange_candle: ExchangeCandle,
    secondary_candle: Optional[ExchangeCandle] = None,
) -> ProviderCandle:
    """Wrap ExchangeCandle into ProviderCandle for testing."""
    return ProviderCandle(
        dt_unix=exchange_candle.dt_unix,
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
        primary_candle=exchange_candle,
        secondary_candle=secondary_candle,
    )


def make_test_candle(
    close: Decimal = Decimal("105"),
    dt_unix: Optional[int] = None,
) -> ProviderCandle:
    """Create a simple ProviderCandle for testing with customizable close price."""
    if dt_unix is None:
        dt_unix = int(datetime.now(timezone.utc).timestamp() * 1000)

    exchange_candle = ExchangeCandle(
        id=1,
        dt_unix=dt_unix,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=close,
        volume=Decimal("1000"),
    )

    return build_provider_candle(exchange_candle)
