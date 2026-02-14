from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from candle_sources.domain.candle_sources import CandleSource
from exchanges.domain import Candle as SourceCandle


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


class TestCandleSource:
    def test_init_assigns_fields(self, trading_pair, timeframe):
        exchange_client = MagicMock()

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        assert source.exchange_client is exchange_client
        assert source.trading_pair == trading_pair
        assert source.timeframe == timeframe

    @pytest.mark.asyncio
    async def test_context_manager_uses_exchange_client(self, trading_pair, timeframe):
        exchange_client = MagicMock()
        exchange_client.__aenter__ = AsyncMock(return_value=exchange_client)
        exchange_client.__aexit__ = AsyncMock(return_value=None)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        async with source as ctx:
            assert ctx is source

        exchange_client.__aenter__.assert_awaited_once()
        exchange_client.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_candles_passes_params(self, trading_pair, timeframe):
        exchange_client = MagicMock()
        exchange_client.fetch_candles = AsyncMock(
            return_value=[build_candle(1700000000000)]
        )
        since = datetime(2024, 1, 1, tzinfo=UTC)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        candles = await source.fetch_candles(since=since, limit=100)

        exchange_client.fetch_candles.assert_awaited_once_with(
            trading_pair=trading_pair,
            timeframe=timeframe,
            since=since,
            limit=100,
        )
        assert candles[0].dt_unix == 1700000000000

    @pytest.mark.asyncio
    async def test_fetch_candles_defaults(self, trading_pair, timeframe):
        exchange_client = MagicMock()
        exchange_client.fetch_candles = AsyncMock(return_value=[])

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        candles = await source.fetch_candles()

        exchange_client.fetch_candles.assert_awaited_once_with(
            trading_pair=trading_pair,
            timeframe=timeframe,
            since=None,
            limit=None,
        )
        assert candles == []

    @pytest.mark.asyncio
    async def test_fetch_candles_partial_args(self, trading_pair, timeframe):
        exchange_client = MagicMock()
        expected = [build_candle(1700000001000)]
        exchange_client.fetch_candles = AsyncMock(return_value=expected)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        candles = await source.fetch_candles(limit=5)

        exchange_client.fetch_candles.assert_awaited_once_with(
            trading_pair=trading_pair,
            timeframe=timeframe,
            since=None,
            limit=5,
        )
        assert candles is expected

    @pytest.mark.asyncio
    async def test_fetch_candles_since_only(self, trading_pair, timeframe):
        exchange_client = MagicMock()
        exchange_client.fetch_candles = AsyncMock(return_value=[])
        since = datetime(2024, 1, 2, tzinfo=UTC)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        await source.fetch_candles(since=since)

        exchange_client.fetch_candles.assert_awaited_once_with(
            trading_pair=trading_pair,
            timeframe=timeframe,
            since=since,
            limit=None,
        )


class TestDomainCandle:
    def test_timestamp_is_utc(self):
        candle = SourceCandle(
            dt_unix=1700000000000,
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
        )

        assert candle.timestamp.tzinfo == UTC
        expected_dt = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert candle.timestamp == expected_dt

    def test_type_up_and_down(self):
        up_candle = SourceCandle(
            dt_unix=1700000000000,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("100"),
            volume=Decimal("10"),
        )
        down_candle = SourceCandle(
            dt_unix=1700000000000,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("99"),
            volume=Decimal("10"),
        )

        assert up_candle.type == "up"
        assert down_candle.type == "down"
