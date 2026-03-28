from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from candle_sources import tasks
from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient
from exchanges.domain import BybitExchange
from exchanges.domain import Candle as DomainCandle
from exchanges.models import Exchange, ExchangeCandle, ExchangeTradingPair, TradingPair


class MockAsyncExchangeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockExchange:
    name = "TestExchange"


class MockTradingPair:
    symbol = "BTC/USDT"


class MockDomainExchangeClient:
    exchange = MockExchange()


class MockDomainSource:
    def __init__(self, candles):
        self._candles = candles
        self.errors = []
        self.exchange_client = MockDomainExchangeClient()
        self.trading_pair = MockTradingPair()
        self.timeframe = "1h"

    async def fetch_candles(self, **kwargs):
        return self._candles


def build_exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Test Exchange"},
    )
    return exchange


def build_trading_pair() -> TradingPair:
    pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
        defaults={
            "symbol": "BTC/USDT",
            "min_amount": Decimal("0.001"),
            "max_amount": Decimal("1000"),
            "fee_percent": Decimal("0.1"),
        },
    )
    return pair


_ec_counter = 0


def build_exchange_trading_pair(
    exchange: Exchange, trading_pair: TradingPair
) -> ExchangeTradingPair:
    return ExchangeTradingPair.objects.create(
        exchange=exchange,
        trading_pair=trading_pair,
        symbol=trading_pair.symbol,
    )


def build_exchange_client(exchange: Exchange) -> ExchangeClient:
    global _ec_counter
    _ec_counter += 1
    return ExchangeClient.objects.create(
        exchange=exchange,
        name=f"Test EC {_ec_counter}",
    )


def build_candle_source(
    exchange_client: ExchangeClient, trading_pair: TradingPair, timeframe: str = "1h"
):
    return CandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=timeframe,
    )


@pytest.mark.django_db(transaction=True)
class TestCandleSourceTasks:
    def test_source_sync_candles_calls_sync(self, monkeypatch):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        source = build_candle_source(exchange_client, trading_pair)
        since = datetime(2024, 1, 1, tzinfo=UTC)

        sync_mock = MagicMock()
        monkeypatch.setattr(CandleSource, "sync_candles", sync_mock)

        tasks.source_sync_candles(source_id=source.id, since=since)

        sync_mock.assert_called_once_with(since=since)

    def test_sources_fetch_last_candles_dispatches_group(self, monkeypatch):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        client_1 = build_exchange_client(exchange)
        client_2 = build_exchange_client(exchange)
        build_candle_source(client_1, trading_pair)
        build_candle_source(client_2, trading_pair)

        captured = {"items": None, "applied": False}

        def fake_group(signatures):
            captured["items"] = list(signatures)

            class Dummy:
                def __or__(self, other):
                    return self

                def apply_async(self):
                    captured["applied"] = True

            return Dummy()

        monkeypatch.setattr(tasks, "group", fake_group)
        monkeypatch.setattr(
            tasks.sources_fetch_last_candles_for_exchange_client,
            "s",
            lambda exchange_client_id: exchange_client_id,
        )

        tasks.sources_fetch_last_candles()

        assert captured["applied"] is True
        assert sorted(captured["items"]) == sorted([client_1.id, client_2.id])

    def test_sources_fetch_last_candles_for_exchange_client_saves_candles(
        self, monkeypatch
    ):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        build_candle_source(exchange_client, trading_pair)

        candles_data = [
            DomainCandle(
                dt_unix=1700000000000,
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            ),
            DomainCandle(
                dt_unix=1700003600000,
                open=Decimal("101"),
                high=Decimal("111"),
                low=Decimal("91"),
                close=Decimal("106"),
                volume=Decimal("1100"),
            ),
        ]

        monkeypatch.setattr(
            ExchangeClient,
            "instantiate",
            lambda self: MockAsyncExchangeClient(),
        )
        monkeypatch.setattr(
            CandleSource,
            "instantiate",
            lambda self, **kwargs: MockDomainSource(candles_data),
        )

        saved = {"calls": []}

        class MockCache:
            async def set_candle(self, **kwargs):
                saved["calls"].append(kwargs)

        monkeypatch.setattr(tasks, "CandleRedisCache", lambda **kw: MockCache())
        monkeypatch.setattr(tasks.sources_sync_from_redis, "delay", MagicMock())

        tasks.sources_fetch_last_candles_for_exchange_client(
            exchange_client_id=exchange_client.id,
        )

        assert len(saved["calls"]) == 2

    def test_sources_fetch_last_candles_for_exchange_client_saves_errors(
        self, monkeypatch
    ):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        build_candle_source(exchange_client, trading_pair)

        class MockDomainSourceWithError:
            def __init__(self):
                from candle_sources.domain import (
                    CandleSourceError as DomainCandleSourceError,
                )

                self.errors = [
                    DomainCandleSourceError(
                        message="Connection failed",
                        type="ExchangeNotAvailable",
                    )
                ]

            async def fetch_candles(self, **kwargs):
                return []

        monkeypatch.setattr(
            ExchangeClient,
            "instantiate",
            lambda self: MockAsyncExchangeClient(),
        )
        monkeypatch.setattr(
            CandleSource,
            "instantiate",
            lambda self, **kwargs: MockDomainSourceWithError(),
        )
        monkeypatch.setattr(tasks, "send_notification", MagicMock())

        class MockCache:
            async def set_candle(self, **kwargs):
                pass

        monkeypatch.setattr(tasks, "CandleRedisCache", lambda **kw: MockCache())

        from candle_sources.models import CandleSourceError as CandleSourceErrorModel

        tasks.sources_fetch_last_candles_for_exchange_client(
            exchange_client_id=exchange_client.id,
        )

        assert CandleSourceErrorModel.objects.count() == 1

    def test_sources_sync_from_redis_bulk_create(self, monkeypatch):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        build_exchange_trading_pair(exchange, trading_pair)
        exchange_client = build_exchange_client(exchange)
        candle_source = build_candle_source(exchange_client, trading_pair)

        candle = DomainCandle(
            dt_unix=1700000000000,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("1000"),
        )

        class MockCache:
            async def get_candles(self, **kwargs):
                return {candle.dt_unix: candle}

        monkeypatch.setattr(tasks, "CandleRedisCache", lambda **kw: MockCache())

        created = {}

        def fake_bulk_create(candles, **kwargs):
            created["candles"] = list(candles)
            created["kwargs"] = kwargs

        monkeypatch.setattr(
            tasks.ExchangeCandle.objects, "bulk_create", fake_bulk_create
        )
        monkeypatch.setattr(tasks, "dispatch_traders_for_sources", MagicMock())
        monkeypatch.setattr(
            tasks, "dispatch_arbitrage_traders_for_sources", MagicMock()
        )

        tasks.sources_sync_from_redis(source_ids=[candle_source.id])

        assert len(created["candles"]) == 1
        assert created["candles"][0].exchange == exchange
        assert created["candles"][0].trading_pair == trading_pair
        assert created["candles"][0].timeframe == candle_source.timeframe

    def test_sources_sync_from_redis_updates_last_synced(self, monkeypatch):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        build_exchange_trading_pair(exchange, trading_pair)
        exchange_client = build_exchange_client(exchange)
        candle_source = build_candle_source(exchange_client, trading_pair)

        assert candle_source.last_synced is None

        candle = DomainCandle(
            dt_unix=1700000000000,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("1000"),
        )

        class MockCache:
            async def get_candles(self, **kwargs):
                return {candle.dt_unix: candle}

        monkeypatch.setattr(tasks, "CandleRedisCache", lambda **kw: MockCache())
        monkeypatch.setattr(tasks, "dispatch_traders_for_sources", MagicMock())
        monkeypatch.setattr(
            tasks, "dispatch_arbitrage_traders_for_sources", MagicMock()
        )

        tasks.sources_sync_from_redis(source_ids=[candle_source.id])

        candle_source.refresh_from_db()
        assert candle_source.last_synced is not None

    def test_sources_fetch_last_candles_query_count_no_sources(self, monkeypatch):
        """
        Тест количества SQL-запросов когда нет источников свечей.

        Проверяет оптимизацию: должен быть только 1 запрос
        для получения списка exchange_client_id.
        """
        # Mock group to avoid task dispatching
        monkeypatch.setattr(tasks, "group", lambda signatures: MagicMock())

        with CaptureQueriesContext(connection) as queries:
            tasks.sources_fetch_last_candles()

        # Ожидаем: 2 запроса (REST exchange_client_ids + WS source_ids)
        assert len(queries) == 2

    def test_sources_fetch_last_candles_for_ec_query_count(self, monkeypatch):
        """
        Тест количества SQL-запросов при fetch свечей в Redis.

        Критично: количество запросов НЕ должно расти
        с количеством источников.
        """
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        build_candle_source(exchange_client, trading_pair)

        candles_data = [
            DomainCandle(
                dt_unix=1700000000000,
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            )
        ]

        monkeypatch.setattr(
            ExchangeClient,
            "instantiate",
            lambda self: MockAsyncExchangeClient(),
        )
        monkeypatch.setattr(
            CandleSource,
            "instantiate",
            lambda self, **kwargs: MockDomainSource(candles_data),
        )

        class MockCache:
            async def set_candle(self, **kwargs):
                pass

        monkeypatch.setattr(tasks, "CandleRedisCache", lambda **kw: MockCache())
        monkeypatch.setattr(tasks.sources_sync_from_redis, "delay", MagicMock())

        with CaptureQueriesContext(connection) as queries:
            tasks.sources_fetch_last_candles_for_exchange_client(
                exchange_client_id=exchange_client.id,
            )

        # Ожидаем:
        # 1. SELECT для получения exchange_client с select_related
        # 2. SELECT для получения candle_sources с select_related
        assert len(queries) == 2

    def test_sources_sync_from_redis_update_existing_candles(self, monkeypatch):
        """
        Тест обновления существующих свечей через update_conflicts.

        Проверяет что при повторном вызове свечи обновляются,
        а не дублируются.
        """
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        build_exchange_trading_pair(exchange, trading_pair)
        exchange_client = build_exchange_client(exchange)
        candle_source = build_candle_source(exchange_client, trading_pair)

        # Создаем начальную свечу
        timestamp = datetime(2024, 11, 14, 10, 0, tzinfo=UTC)
        ExchangeCandle.objects.create(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe="1h",
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("102"),
            volume=Decimal("1000"),
        )

        updated_candle = DomainCandle(
            dt_unix=int(timestamp.timestamp() * 1000),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("1500"),
        )

        class MockCache:
            async def get_candles(self, **kwargs):
                return {updated_candle.dt_unix: updated_candle}

        monkeypatch.setattr(tasks, "CandleRedisCache", lambda **kw: MockCache())
        monkeypatch.setattr(tasks, "dispatch_traders_for_sources", MagicMock())
        monkeypatch.setattr(
            tasks, "dispatch_arbitrage_traders_for_sources", MagicMock()
        )

        tasks.sources_sync_from_redis(source_ids=[candle_source.id])

        # Проверяем что свеча обновилась, а не продублировалась
        candles = ExchangeCandle.objects.filter(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe="1h",
            timestamp=timestamp,
        )
        assert candles.count() == 1

        result = candles.first()
        assert result.high == Decimal("110")
        assert result.low == Decimal("90")
        assert result.close == Decimal("105")
        assert result.volume == Decimal("1500")
