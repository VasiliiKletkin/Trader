import asyncio
from datetime import datetime

from celery import group, shared_task
from django.conf import settings
from django.utils import timezone

from arbitrage_traders.tasks import dispatch_arbitrage_traders_for_sources
from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import (
    CandleSource,
    CandleSourceError,
    CandleSourceMode,
)
from core.utils.async_utils import run_with_exchange_client
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.models import ExchangeCandle
from telegram_bots.tasks import send_notification
from traders.tasks import dispatch_traders_for_sources


@shared_task()
def source_sync_candles(source_id: int, since: datetime):
    source = CandleSource.objects.get(id=source_id)
    source.sync_candles(since=since)


@shared_task()
def sources_fetch_last_candles():
    tasks = []

    # REST-источники — fanout по exchange_client
    rest_client_ids = (
        CandleSource.active_objects.filter(mode=CandleSourceMode.REST)
        .values_list("exchange_client_id", flat=True)
        .distinct()
    )
    tasks.extend(
        sources_fetch_last_candles_for_exchange_client.s(
            exchange_client_id=client_id,
        )
        for client_id in rest_client_ids
    )

    # WS-источники — одна задача на синхронизацию из Redis
    ws_source_ids = list(
        CandleSource.active_objects.filter(mode=CandleSourceMode.WEBSOCKET).values_list(
            "id", flat=True
        )
    )
    if ws_source_ids:
        tasks.append(sources_sync_from_redis.s(source_ids=ws_source_ids))

    if tasks:
        group(tasks).apply_async()


@shared_task(queue="candle_sources_fetch")
def sources_sync_from_redis(source_ids: list[int]):
    """Читает свечи из Redis (WS-источники) и сохраняет в PostgreSQL."""
    redis_settings = settings.REDIS
    cache = CandleRedisCache(
        host=str(redis_settings["HOST"]),
        port=int(redis_settings["PORT"]),
        db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
        password=str(redis_settings["PASSWORD"]) or None,
    )

    candle_sources_qs = list(
        CandleSource.active_objects.filter(
            id__in=source_ids,
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "trading_pair",
        )
    )

    if not candle_sources_qs:
        return

    async def _fetch_all():
        candles = []
        synced_source_ids = []
        for source in candle_sources_qs:
            domain_source = source.instantiate()
            cached = await cache.get_candles(
                exchange=domain_source.exchange_client.exchange,
                trading_pair=domain_source.trading_pair,
                timeframe=domain_source.timeframe,
            )
            if not cached:
                continue

            synced_source_ids.append(source.pk)
            for candle in cached.values():
                candles.append(
                    ExchangeCandle(
                        exchange=source.exchange_client.exchange,
                        timeframe=source.timeframe,
                        trading_pair=source.trading_pair,
                        timestamp=candle.timestamp,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                    )
                )
        return candles, synced_source_ids

    candles, synced_source_ids = asyncio.run(_fetch_all())

    if synced_source_ids:
        CandleSource.objects.filter(id__in=synced_source_ids).update(
            last_synced=timezone.now()
        )

    if not candles:
        return

    ExchangeCandle.objects.bulk_create(
        candles,
        batch_size=settings.BULK_BATCH_SIZE,
        update_conflicts=True,
        update_fields=["open", "high", "low", "close", "volume"],
        unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
    )

    source_ids = [s.pk for s in candle_sources_qs]
    dispatch_traders_for_sources.delay(source_ids=source_ids)
    dispatch_arbitrage_traders_for_sources.delay(source_ids=source_ids)


@shared_task(queue="candle_sources_fetch")
def sources_fetch_last_candles_for_exchange_client(exchange_client_id: int):
    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)

    candle_sources = list(
        CandleSource.active_objects.filter(
            exchange_client=exchange_client,
        )
        .exclude(mode=CandleSourceMode.WEBSOCKET)
        .select_related(
            "exchange_client",
            "trading_pair",
            "exchange_client__exchange",
        )
    )

    domain_exchange_client = exchange_client.instantiate()
    domain_sources = [
        source.instantiate(domain_exchange_client=domain_exchange_client)
        for source in candle_sources
    ]
    results: list[list[DomainCandle]] = asyncio.run(
        run_with_exchange_client(
            exchange_client=domain_exchange_client,
            tasks=[ds.fetch_candles(limit=2) for ds in domain_sources],
        )
    )
    source_errors = []
    error_source_ids: set[int] = set()
    for source, domain_source in zip(candle_sources, domain_sources):
        for err in domain_source.errors:
            error_source_ids.add(source.pk)
            source_errors.append(
                CandleSourceError(
                    candle_source=source,
                    message=err.message,
                    type=err.type,
                    traceback=err.traceback or "",
                )
            )
            send_notification.delay(
                message=(
                    f"Ошибка загрузки свечей для источника: {source}\n"
                    f"{err.type}: {err.message}"
                ),
            )

    if source_errors:
        CandleSourceError.objects.bulk_create(source_errors)

    candles = []
    for source, result in zip(candle_sources, results):
        for c in result:
            candles.append(
                ExchangeCandle(
                    exchange=source.exchange_client.exchange,
                    timeframe=source.timeframe,
                    trading_pair=source.trading_pair,
                    timestamp=c.timestamp,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume,
                )
            )

    synced_source_ids = [s.pk for s in candle_sources if s.pk not in error_source_ids]
    if synced_source_ids:
        CandleSource.objects.filter(id__in=synced_source_ids).update(
            last_synced=timezone.now()
        )

    if not candles:
        return

    ExchangeCandle.objects.bulk_create(
        candles,
        batch_size=settings.BULK_BATCH_SIZE,
        update_conflicts=True,
        update_fields=["open", "high", "low", "close", "volume"],
        unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
    )

    source_ids = [s.pk for s in candle_sources]
    dispatch_traders_for_sources.delay(source_ids=source_ids)
    dispatch_arbitrage_traders_for_sources.delay(source_ids=source_ids)
