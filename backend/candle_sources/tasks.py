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
from exchange_clients.models import ExchangeClient
from exchanges.models import ExchangeCandle
from telegram_bots.tasks import send_notification
from traders.tasks import dispatch_traders_for_sources


@shared_task()
def source_sync_candles(source_id: int, since: datetime):
    source = CandleSource.objects.get(id=source_id)
    source.sync_candles(since=since)


@shared_task(queue="candle_sources_fetch")
def sources_fetch_last_candles():
    # REST — fetch
    rest_sources = CandleSource.active_objects.filter(mode=CandleSourceMode.REST)
    if rest_sources.exists():
        fetch_tasks = group(
            sources_fetch_last_candles_for_exchange_client.s(
                exchange_client_id=cid,
            )
            for cid in rest_sources.values_list(
                "exchange_client_id", flat=True
            ).distinct()
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


@shared_task(queue="candle_sources_fetch")
def sources_fetch_last_candles_for_exchange_client(exchange_client_id: int):
    """Загружает свечи с биржи, сохраняет в Redis-кеш и запускает sync."""
    redis_settings = settings.REDIS
    cache = CandleRedisCache(
        host=str(redis_settings["HOST"]),
        port=int(redis_settings["PORT"]),
        db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
        password=str(redis_settings["PASSWORD"]) or None,
    )

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)

    candle_sources_qs = list(
        CandleSource.active_objects.filter(
            exchange_client=exchange_client,
            mode=CandleSourceMode.REST,
        ).select_related(
            "exchange_client",
            "trading_pair",
            "exchange_client__exchange",
        )
    )

    if not candle_sources_qs:
        return

    domain_exchange = exchange_client.exchange.instantiate()

    async def _run():
        rpc_client = exchange_client.get_rpc_client()
        domain_sources = [
            source.instantiate(domain_exchange_client=rpc_client)
            for source in candle_sources_qs
        ]
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


@shared_task(queue="candle_sources_fetch")
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
            "exchange_client",
            "exchange_client__exchange",
            "trading_pair",
        )
    )

    if not candle_sources_qs:
        return

    async def cache_get_candles():
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
            timeframe = source.timeframe

            for candle in cached.values():
                candles.append(
                    ExchangeCandle(
                        exchange=source.exchange_client.exchange,
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
