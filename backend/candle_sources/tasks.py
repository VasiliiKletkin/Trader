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
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import Exchange, ExchangeCandle
from telegram_bots.tasks import send_notification
from traders.tasks import dispatch_traders_for_sources


@shared_task(queue="candle_sources")
def source_sync_candles(source_id: int, since: datetime):
    source = CandleSource.objects.get(id=source_id)
    source.sync_candles(since=since)


@shared_task(queue="candle_sources")
def delete_candles(exchange_id: int, trading_pair_id: int, timeframe: str):
    """Удалить свечи по параметрам источника."""
    ExchangeCandle.objects.filter(
        exchange_id=exchange_id,
        trading_pair_id=trading_pair_id,
        timeframe=timeframe,
    ).delete()


@shared_task()
def sources_fetch_last_candles():
    # REST — группировка по бирже, а не по клиенту
    rest_sources = CandleSource.active_objects.filter(mode=CandleSourceMode.REST)
    if rest_sources.exists():
        fetch_tasks = group(
            sources_fetch_last_candles_for_exchange.s(
                exchange_id=eid,
            )
            for eid in rest_sources.values_list("exchange_id", flat=True).distinct()
        )
        fetch_tasks.apply_async()

    # WS — уже в Redis, сразу sync
    ws_source = CandleSource.active_objects.filter(
        mode=CandleSourceMode.WEBSOCKET,
    )
    if ws_source.exists():
        sources_sync_from_redis.delay(
            source_ids=list(ws_source.values_list("id", flat=True))
        )


@shared_task()
def sources_fetch_last_candles_for_exchange(exchange_id: int):
    """Загружает свечи через публичный клиент, сохраняет в Redis-кеш."""
    exchange: Exchange = Exchange.active_objects.get(id=exchange_id)

    candle_sources_qs = list(
        CandleSource.active_objects.filter(
            exchange=exchange,
            mode=CandleSourceMode.REST,
        ).select_related(
            "exchange",
            "trading_pair",
        )
    )

    if not candle_sources_qs:
        return

    async def _run():
        redis_settings = settings.REDIS
        cache = CandleRedisCache(
            host=str(redis_settings["HOST"]),
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=str(redis_settings["PASSWORD"]) or None,
        )
        public_client = exchange.instantiate_public_client()
        domain_exchange = public_client.exchange
        domain_sources = [
            source.instantiate(domain_exchange_client=public_client)
            for source in candle_sources_qs
        ]

        async with public_client:
            results = await asyncio.gather(
                *[ds.fetch_candles(limit=2) for ds in domain_sources],
            )
        for domain_source, result in zip(domain_sources, results):
            for candle in result:
                await cache.set_candle(
                    exchange=domain_exchange,
                    trading_pair=domain_source.trading_pair,
                    timeframe=domain_source.timeframe,
                    candle=candle,
                )
        return domain_sources

    domain_sources = asyncio.run(_run())

    source_errors = []
    synced_source_ids = []

    for source, domain_source in zip(candle_sources_qs, domain_sources):
        has_error = False
        for err in domain_source.errors:
            has_error = True
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

        if not has_error:
            synced_source_ids.append(source.pk)

    if source_errors:
        CandleSourceError.objects.bulk_create(source_errors)

    if not synced_source_ids:
        return

    sources_sync_from_redis.delay(source_ids=synced_source_ids)


@shared_task()
def sources_sync_from_redis(source_ids: list[int]):
    """Читает свечи из Redis и сохраняет в PostgreSQL."""
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
        ).select_related(
            "exchange",
            "trading_pair",
        )
    )

    if not candle_sources_qs:
        return

    async def cache_get_candles():
        candles = []
        synced_source_ids = []
        for source in candle_sources_qs:
            exchange = source.exchange.instantiate()
            cached = await cache.get_candles(
                exchange=exchange,
                trading_pair=source.trading_pair.instantiate(exchange=source.exchange),
                timeframe=DomainTimeframe(source.timeframe),
            )
            if not cached:
                continue

            synced_source_ids.append(source.pk)
            timeframe = source.timeframe

            for candle in cached.values():
                candles.append(
                    ExchangeCandle(
                        exchange=source.exchange,
                        timeframe=timeframe,
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

    candles, synced_source_ids = asyncio.run(cache_get_candles())

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
