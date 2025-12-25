from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from candle_sources.domain.candle_sources import CandleSource
from candle_sources.domain.shemas import Candle as SourceCandle
from exchanges.domain import Candle, Timeframe, TradingPair


def build_trading_pair() -> TradingPair:
    return TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )


def build_candle(dt_unix: int) -> Candle:
    return Candle(
        dt_unix=dt_unix,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1000"),
    )


class TestCandleSource:
    def test_init_assigns_fields(self):
        exchange_client = MagicMock()
        trading_pair = build_trading_pair()
        timeframe = Timeframe.ONE_HOUR

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        assert source.exchange_client is exchange_client
        assert source.trading_pair == trading_pair
        assert source.timeframe == timeframe

    @pytest.mark.asyncio
    async def test_context_manager_uses_exchange_client(self):
        exchange_client = MagicMock()
        exchange_client.__aenter__ = AsyncMock(return_value=exchange_client)
        exchange_client.__aexit__ = AsyncMock(return_value=None)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=build_trading_pair(),
            timeframe=Timeframe.ONE_HOUR,
        )

        async with source as ctx:
            assert ctx is source

        exchange_client.__aenter__.assert_awaited_once()
        exchange_client.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pull_candles_passes_params(self):
        exchange_client = MagicMock()
        exchange_client.get_candles = AsyncMock(
            return_value=[build_candle(1700000000000)]
        )
        trading_pair = build_trading_pair()
        timeframe = Timeframe.ONE_HOUR
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        candles = await source.pull_candles(since=since, limit=100)

        exchange_client.get_candles.assert_awaited_once_with(
            trading_pair=trading_pair.symbol,
            timeframe=timeframe.value,
            since=since,
            limit=100,
        )
        assert candles[0].dt_unix == 1700000000000

    @pytest.mark.asyncio
    async def test_pull_candles_defaults(self):
        exchange_client = MagicMock()
        exchange_client.get_candles = AsyncMock(return_value=[])
        trading_pair = build_trading_pair()
        timeframe = Timeframe.ONE_HOUR

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        candles = await source.pull_candles()

        exchange_client.get_candles.assert_awaited_once_with(
            trading_pair=trading_pair.symbol,
            timeframe=timeframe.value,
            since=None,
            limit=None,
        )
        assert candles == []

    @pytest.mark.asyncio
    async def test_pull_candles_partial_args(self):
        exchange_client = MagicMock()
        expected = [build_candle(1700000001000)]
        exchange_client.get_candles = AsyncMock(return_value=expected)
        trading_pair = build_trading_pair()
        timeframe = Timeframe.ONE_HOUR

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        candles = await source.pull_candles(limit=5)

        exchange_client.get_candles.assert_awaited_once_with(
            trading_pair=trading_pair.symbol,
            timeframe=timeframe.value,
            since=None,
            limit=5,
        )
        assert candles is expected

    @pytest.mark.asyncio
    async def test_pull_candles_since_only(self):
        exchange_client = MagicMock()
        exchange_client.get_candles = AsyncMock(return_value=[])
        trading_pair = build_trading_pair()
        timeframe = Timeframe.ONE_HOUR
        since = datetime(2024, 1, 2, tzinfo=timezone.utc)

        source = CandleSource(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe=timeframe,
        )

        await source.pull_candles(since=since)

        exchange_client.get_candles.assert_awaited_once_with(
            trading_pair=trading_pair.symbol,
            timeframe=timeframe.value,
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

        assert candle.timestamp.tzinfo == timezone.utc
        assert candle.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

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
