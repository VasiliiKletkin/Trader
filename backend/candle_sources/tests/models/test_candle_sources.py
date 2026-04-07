from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone as django_timezone

from candle_sources.models import CandleSource
from exchanges.domain import BybitExchange
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.domain.exchanges import BinanceExchange
from exchanges.models import Exchange, ExchangeCandle, ExchangeTradingPair, TradingPair


def build_exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Test Exchange"},
    )
    return exchange


def build_trading_pair() -> TradingPair:
    pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
    )
    return pair


def build_candle_source(exchange: Exchange, trading_pair: TradingPair):
    return CandleSource.objects.create(
        exchange=exchange,
        trading_pair=trading_pair,
        timeframe="1h",
    )


def create_exchange_candles(
    exchange: Exchange,
    trading_pair: TradingPair,
    timeframe: str,
    base_time: datetime,
    count: int,
) -> list[ExchangeCandle]:
    candles = []
    for i in range(count):
        candles.append(
            ExchangeCandle.objects.create(
                exchange=exchange,
                timeframe=timeframe,
                trading_pair=trading_pair,
                timestamp=base_time + timedelta(hours=i),
                open=Decimal("100") + i,
                high=Decimal("110") + i,
                low=Decimal("90") + i,
                close=Decimal("105") + i,
                volume=Decimal("1000"),
            )
        )
    return candles


@pytest.mark.django_db
class TestCandleSourceModel:
    def test_str(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)

        assert str(source) == f"{exchange} | {trading_pair} | {source.timeframe}"

    def test_active_objects_filters_inactive(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        active_source = build_candle_source(exchange, trading_pair)
        other_pair, _ = TradingPair.objects.get_or_create(
            name="ETH/USDT",
        )
        inactive_source = build_candle_source(
            exchange,
            other_pair,
        )
        inactive_source.is_active = False
        inactive_source.save()

        sources = list(CandleSource.active_objects.all())
        assert active_source in sources
        assert inactive_source not in sources

    def test_instantiate_uses_exchange_trading_pair(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        ExchangeTradingPair.objects.create(
            exchange=exchange, trading_pair=trading_pair, symbol="BTC/USDT:USDT"
        )
        source = build_candle_source(exchange, trading_pair)

        domain_source = source.instantiate(domain_exchange_client=SimpleNamespace())

        assert isinstance(domain_source.trading_pair, DomainTradingPair)
        assert domain_source.trading_pair.symbol == "BTC/USDT:USDT"

    def test_delete_all_candles(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)
        other_exchange, _ = Exchange.objects.get_or_create(
            class_name=BinanceExchange.__name__,
            defaults={"name": "Other Exchange"},
        )
        other_pair, _ = TradingPair.objects.get_or_create(
            name="ETH/USDT",
        )

        create_exchange_candles(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=source.timeframe,
            base_time=datetime(2024, 1, 1, tzinfo=UTC),
            count=3,
        )
        create_exchange_candles(
            exchange=other_exchange,
            trading_pair=other_pair,
            timeframe=source.timeframe,
            base_time=datetime(2024, 1, 1, tzinfo=UTC),
            count=2,
        )

        source.delete_all_candles()

        assert (
            ExchangeCandle.objects.filter(
                exchange=exchange, trading_pair=trading_pair
            ).count()
            == 0
        )
        assert ExchangeCandle.objects.filter(exchange=other_exchange).count() == 2

    def test_candles_count(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)
        base_time = datetime(2024, 1, 1, tzinfo=UTC)

        create_exchange_candles(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=source.timeframe,
            base_time=base_time,
            count=4,
        )

        assert source.candles.count() == 4

    def test_get_candles_range_sorted(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)
        base_time = datetime(2024, 1, 1, tzinfo=UTC)

        create_exchange_candles(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=source.timeframe,
            base_time=base_time,
            count=6,
        )

        candles = list(
            source.get_candles(
                start=base_time + timedelta(hours=1),
                end=base_time + timedelta(hours=3),
            )
        )
        assert [c.timestamp for c in candles] == [
            base_time + timedelta(hours=1),
            base_time + timedelta(hours=2),
            base_time + timedelta(hours=3),
        ]

    def test_get_last_candles_returns_oldest_first(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)
        base_time = datetime(2024, 1, 1, tzinfo=UTC)

        create_exchange_candles(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=source.timeframe,
            base_time=base_time,
            count=5,
        )

        candles = list(source.get_last_candles(2))
        assert [c.timestamp for c in candles] == [
            base_time + timedelta(hours=3),
            base_time + timedelta(hours=4),
        ]

    def test_get_candle_iterator_filters_range(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)
        base_time = datetime(2024, 1, 1, tzinfo=UTC)

        create_exchange_candles(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=source.timeframe,
            base_time=base_time,
            count=5,
        )

        candles = list(
            source.get_candle_iterator(
                start=base_time + timedelta(hours=1),
                end=base_time + timedelta(hours=3),
            )
        )
        assert [c.timestamp for c in candles] == [
            base_time + timedelta(hours=1),
            base_time + timedelta(hours=2),
            base_time + timedelta(hours=3),
        ]


@pytest.mark.django_db
class TestCandleSourcePullSync:
    def test_sync_candles_rejects_future_since(self):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)

        future = django_timezone.now() + timedelta(days=1)
        with pytest.raises(ValueError, match="Since не может быть в будущем"):
            source.sync_candles(since=future)

    def test_sync_candles_sets_errors_on_exception(self, monkeypatch):
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)

        def raise_error(self):
            raise RuntimeError("boom")

        monkeypatch.setattr(Exchange, "instantiate_public_client", raise_error)

        total = source.sync_candles()

        assert total == 0
        error = source.errors.first()
        assert error is not None
        assert error.message == "boom"

    def test_sync_candles_deduplicates_via_update_conflicts(self):
        """Дубликаты по timestamp обрабатываются bulk_create(update_conflicts)."""
        exchange = build_exchange()
        trading_pair = build_trading_pair()
        source = build_candle_source(exchange, trading_pair)
        timestamp = datetime(2024, 1, 1, tzinfo=UTC)

        # Первая вставка
        ExchangeCandle.objects.bulk_create(
            [
                ExchangeCandle(
                    exchange=exchange,
                    timeframe=source.timeframe,
                    trading_pair=trading_pair,
                    timestamp=timestamp,
                    open=Decimal("100"),
                    high=Decimal("110"),
                    low=Decimal("90"),
                    close=Decimal("105"),
                    volume=Decimal("1000"),
                )
            ],
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
        )

        # Вторая вставка с тем же timestamp — обновит значения
        ExchangeCandle.objects.bulk_create(
            [
                ExchangeCandle(
                    exchange=exchange,
                    timeframe=source.timeframe,
                    trading_pair=trading_pair,
                    timestamp=timestamp,
                    open=Decimal("101"),
                    high=Decimal("111"),
                    low=Decimal("91"),
                    close=Decimal("106"),
                    volume=Decimal("1100"),
                )
            ],
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
        )

        assert ExchangeCandle.objects.filter(timestamp=timestamp).count() == 1
        saved = ExchangeCandle.objects.get(timestamp=timestamp)
        assert saved.close == Decimal("106")
