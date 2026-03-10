from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from candle_sources import tasks
from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient
from exchanges.domain import BybitExchange
from exchanges.domain import Candle as DomainCandle
from exchanges.models import Exchange, ExchangeCandle, TradingPair


class MockAsyncExchangeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockDomainSource:
    def __init__(self, candles):
        self._candles = candles
        self.errors = []

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


@pytest.mark.django_db
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

    def test_sources_fetch_last_candles_for_exchange_client_bulk_create(
        self, monkeypatch
    ):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        candle_source = build_candle_source(exchange_client, trading_pair)

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

        created = {}

        def fake_bulk_create(candles, **kwargs):
            created["candles"] = list(candles)
            created["kwargs"] = kwargs

        monkeypatch.setattr(
            tasks.ExchangeCandle.objects, "bulk_create", fake_bulk_create
        )
        traders_process_mock = MagicMock()
        monkeypatch.setattr(tasks, "traders_process_by_sources", traders_process_mock)

        tasks.sources_fetch_last_candles_for_exchange_client(
            exchange_client_id=exchange_client.id
        )

        assert len(created["candles"]) == 2
        assert created["candles"][0].exchange == exchange
        assert created["candles"][0].trading_pair == trading_pair
        assert created["candles"][0].timeframe == candle_source.timeframe
        traders_process_mock.assert_called_once()

    def test_sources_fetch_last_candles_for_exchange_client_updates_last_synced(
        self, monkeypatch
    ):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        candle_source = build_candle_source(exchange_client, trading_pair)

        assert candle_source.last_synced is None

        candles_data = [
            DomainCandle(
                dt_unix=1700000000000,
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
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
        monkeypatch.setattr(tasks, "traders_process_by_sources", MagicMock())
        monkeypatch.setattr(tasks, "arbitrage_traders_process_by_sources", MagicMock())

        tasks.sources_fetch_last_candles_for_exchange_client(
            exchange_client_id=exchange_client.id
        )

        candle_source.refresh_from_db()
        assert candle_source.last_synced is not None

    def test_sources_fetch_last_candles_for_exchange_client_no_last_synced_on_error(
        self, monkeypatch
    ):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        candle_source = build_candle_source(exchange_client, trading_pair)

        assert candle_source.last_synced is None

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
        monkeypatch.setattr(tasks, "traders_process_by_sources", MagicMock())
        monkeypatch.setattr(tasks, "arbitrage_traders_process_by_sources", MagicMock())
        monkeypatch.setattr(tasks, "send_notification", MagicMock())

        tasks.sources_fetch_last_candles_for_exchange_client(
            exchange_client_id=exchange_client.id
        )

        candle_source.refresh_from_db()
        assert candle_source.last_synced is None

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

    def test_sources_fetch_last_candles_for_exchange_client_query_count(
        self, monkeypatch
    ):
        """
        Тест количества SQL-запросов при получении свечей для клиента.

        Критично: количество запросов НЕ должно расти
        с количеством источников благодаря bulk_create.
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
        monkeypatch.setattr(tasks, "traders_process_by_sources", MagicMock())
        monkeypatch.setattr(tasks, "arbitrage_traders_process_by_sources", MagicMock())

        with CaptureQueriesContext(connection) as queries:
            tasks.sources_fetch_last_candles_for_exchange_client(
                exchange_client_id=exchange_client.id
            )

        # Ожидаем:
        # 1. SELECT для получения exchange_client с select_related
        # 2. SELECT для получения candle_sources с select_related
        # 3. UPDATE last_synced для успешных источников
        # 4. INSERT для bulk_create свечей
        assert len(queries) == 4

    def test_sources_fetch_last_candles_for_exchange_client_multiple_sources(
        self, monkeypatch
    ):
        """
        Тест с несколькими источниками свечей.

        Проверяет что bulk_create работает правильно
        при наличии нескольких источников.
        """
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)

        # Создаем 3 источника с разными таймфреймами
        build_candle_source(exchange_client, trading_pair, timeframe="1h")
        build_candle_source(exchange_client, trading_pair, timeframe="4h")
        build_candle_source(exchange_client, trading_pair, timeframe="1d")

        all_candles = [
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
            DomainCandle(
                dt_unix=1700007200000,
                open=Decimal("102"),
                high=Decimal("112"),
                low=Decimal("92"),
                close=Decimal("107"),
                volume=Decimal("1200"),
            ),
        ]

        # Каждый источник возвращает по одной свече
        source_idx = iter(range(3))

        def make_source(self, **kwargs):
            idx = next(source_idx)
            return MockDomainSource([all_candles[idx]])

        monkeypatch.setattr(
            ExchangeClient,
            "instantiate",
            lambda self: MockAsyncExchangeClient(),
        )
        monkeypatch.setattr(CandleSource, "instantiate", make_source)
        monkeypatch.setattr(tasks, "traders_process_by_sources", MagicMock())

        with CaptureQueriesContext(connection) as queries:
            tasks.sources_fetch_last_candles_for_exchange_client(
                exchange_client_id=exchange_client.id
            )

        # Ожидаем фиксированное количество запросов
        # 1. SELECT exchange_client
        # 2. SELECT candle_sources
        # 3-6. bulk_create с update_conflicts (может быть несколько INSERTs)
        # Важно: количество НЕ растет с количеством источников по N+1
        assert len(queries) <= 10, f"Слишком много запросов: {len(queries)}"

        # Проверяем что все 3 свечи были созданы
        assert ExchangeCandle.objects.count() == 3

    def test_sources_fetch_last_candles_update_existing_candles(self, monkeypatch):
        """
        Тест обновления существующих свечей через update_conflicts.

        Проверяет что при повторном вызове свечи обновляются,
        а не дублируются.
        """
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        exchange_client = build_exchange_client(exchange)
        build_candle_source(exchange_client, trading_pair)

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

        updated_candles = [
            DomainCandle(
                dt_unix=int(timestamp.timestamp() * 1000),
                open=Decimal("100"),
                high=Decimal("110"),  # Обновленный high
                low=Decimal("90"),  # Обновленный low
                close=Decimal("105"),  # Обновленный close
                volume=Decimal("1500"),  # Обновленный volume
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
            lambda self, **kwargs: MockDomainSource(updated_candles),
        )
        monkeypatch.setattr(tasks, "traders_process_by_sources", MagicMock())

        # Вызываем task
        tasks.sources_fetch_last_candles_for_exchange_client(
            exchange_client_id=exchange_client.id
        )

        # Проверяем что свеча обновилась, а не продублировалась
        candles = ExchangeCandle.objects.filter(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe="1h",
            timestamp=timestamp,
        )
        assert candles.count() == 1

        updated_candle = candles.first()
        assert updated_candle.high == Decimal("110")
        assert updated_candle.low == Decimal("90")
        assert updated_candle.close == Decimal("105")
        assert updated_candle.volume == Decimal("1500")


class FakeQuerySet:
    def __init__(self, traders):
        self._traders = traders

    def select_related(self, *args, **kwargs):
        return self

    def iterator(self):
        return iter(self._traders)


def make_trader(pk: int, exchange_client_id: int):
    exchange_client = SimpleNamespace(pk=exchange_client_id)
    return SimpleNamespace(pk=pk, exchange_client=exchange_client)


class TestTradersProcessBySources:
    def test_groups_by_exchange_client(self, monkeypatch):
        traders = [
            make_trader(1, 10),
            make_trader(2, 20),
            make_trader(3, 10),
        ]
        candle_sources = [SimpleNamespace(pk=1)]

        monkeypatch.setattr(
            tasks.Trader.objects,
            "filter",
            lambda *args, **kwargs: FakeQuerySet(traders),
        )

        captured = {"items": None, "applied": False}

        def fake_group(signatures):
            captured["items"] = list(signatures)

            class Dummy:
                def apply_async(self):
                    captured["applied"] = True

            return Dummy()

        monkeypatch.setattr(tasks, "group", fake_group)
        monkeypatch.setattr(
            tasks.traders_process_for_exchange_client,
            "s",
            lambda exchange_client_id, traders_ids: (exchange_client_id, traders_ids),
        )

        tasks.traders_process_by_sources(candle_sources=candle_sources)

        assert captured["applied"] is True
        grouped = dict(captured["items"])
        assert grouped[10] == [1, 3]
        assert grouped[20] == [2]

    def test_no_traders(self, monkeypatch):
        candle_sources = [SimpleNamespace(pk=1)]
        monkeypatch.setattr(
            tasks.Trader.objects,
            "filter",
            lambda *args, **kwargs: FakeQuerySet([]),
        )
        group_mock = MagicMock()
        monkeypatch.setattr(tasks, "group", group_mock)

        tasks.traders_process_by_sources(candle_sources=candle_sources)

        group_mock.assert_not_called()
