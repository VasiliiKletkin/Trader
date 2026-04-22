import asyncio
from datetime import datetime
from typing import NamedTuple

from celery import group, shared_task
from django.conf import settings
from django.utils import timezone

from arbitrage_traders.tasks import dispatch_arbitrage_traders_for_sources
from candle_sources.domain import CandleSource as DomainCandleSource
from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import (
    CandleSource,
    CandleSourceError,
)
from candle_sources.schemas import CandleSourceStatus
from exchange_clients.domain.base import AbstractExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Exchange as DomainExchange
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.models import Exchange, ExchangeCandle
from exchanges.schemas import CandleSourceMode
from telegram_bots.tasks import send_notification
from traders.tasks import dispatch_traders_for_sources


class _PreparedSource(NamedTuple):
    source_id: int
    exchange: DomainExchange
    trading_pair: DomainTradingPair
    timeframe: DomainTimeframe


@shared_task(queue="candle_source")
def candle_source_sync_candles(source_id: int, since: datetime):
    source = CandleSource.objects.get(id=source_id)
    source.sync_candles(since=since)


@shared_task(queue="candle_source")
def candle_source_delete_candles(source_id: int, before: datetime):
    """Удалить свечи старше указанной даты."""
    source = CandleSource.objects.get(id=source_id)
    source.delete_candles(before=before)


@shared_task(queue="candle_source")
def candle_source_clear_all_data(source_id: int):
    """Очистить все данные источника: свечи, ошибки, last_synced."""
    source = CandleSource.objects.get(id=source_id)
    source.clear_all_data()


@shared_task(queue="candle_source")
def candle_source_clear_all_errors(source_id: int):
    """Удалить все ошибки источника."""
    source = CandleSource.objects.get(id=source_id)
    source.clear_all_errors()


@shared_task()
def candle_sources_fetch_last_candles():
    # REST — группировка по бирже, а не по клиенту
    rest_sources = CandleSource.objects.exclude(
        status=CandleSourceStatus.DISABLED
    ).filter(
        exchange__candle_source_mode=CandleSourceMode.REST,
    )
    if rest_sources.exists():
        fetch_tasks = group(
            candle_sources_fetch_last_candles_for_exchange.s(
                exchange_id=eid,
            )
            for eid in rest_sources.values_list("exchange_id", flat=True).distinct()
        )
        fetch_tasks.apply_async()

    # WS — уже в Redis, сразу sync
    ws_source = CandleSource.objects.exclude(status=CandleSourceStatus.DISABLED).filter(
        exchange__candle_source_mode=CandleSourceMode.WEBSOCKET,
    )
    if ws_source.exists():
        candle_sources_sync_from_redis.delay(
            source_ids=list(ws_source.values_list("id", flat=True))
        )


@shared_task()
def candle_sources_fetch_last_candles_for_exchange(exchange_id: int):
    """Загружает свечи через публичный клиент, сохраняет в Redis-кеш."""
    exchange: Exchange = Exchange.active_objects.get(id=exchange_id)

    candle_sources_qs = list(
        CandleSource.objects.exclude(status=CandleSourceStatus.DISABLED)
        .filter(
            exchange=exchange,
        )
        .select_related(
            "exchange",
            "trading_pair",
        )
    )

    if not candle_sources_qs:
        return

    # Доменные объекты инстанциируются синхронно до asyncio.run,
    # т.к. instantiate() читает ORM (SynchronousOnlyOperation внутри event loop).
    public_client: AbstractExchangeClient = exchange.instantiate_public_client()
    domain_exchange: DomainExchange = public_client.exchange
    domain_sources: list[DomainCandleSource] = [
        source.instantiate(domain_exchange_client=public_client)
        for source in candle_sources_qs
    ]

    async def _run(
        public_client: AbstractExchangeClient,
        domain_exchange: DomainExchange,
        domain_sources: list[DomainCandleSource],
    ) -> None:
        redis_settings = settings.REDIS
        cache = CandleRedisCache(
            host=str(redis_settings["HOST"]),
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=str(redis_settings["PASSWORD"]) or None,
        )

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

    asyncio.run(_run(public_client, domain_exchange, domain_sources))

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

    candle_sources_sync_from_redis.delay(source_ids=synced_source_ids)


@shared_task()
def candle_sources_sync_from_redis(source_ids: list[int]):
    """Читает свечи из Redis и сохраняет в PostgreSQL."""
    redis_settings = settings.REDIS
    cache = CandleRedisCache(
        host=str(redis_settings["HOST"]),
        port=int(redis_settings["PORT"]),
        db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
        password=str(redis_settings["PASSWORD"]) or None,
    )

    candle_sources_qs = list(
        CandleSource.objects.exclude(status=CandleSourceStatus.DISABLED)
        .filter(
            id__in=source_ids,
        )
        .select_related(
            "exchange",
            "trading_pair",
        )
    )

    if not candle_sources_qs:
        return

    # В async передаются только доменные сущности и примитивы.
    # ORM-объекты связываются обратно после asyncio.run через source_id.
    source_by_pk: dict[int, CandleSource] = {
        source.pk: source for source in candle_sources_qs
    }
    prepared_domain: list[_PreparedSource] = [
        _PreparedSource(
            source_id=source.pk,
            exchange=source.exchange.instantiate(),
            trading_pair=source.trading_pair.instantiate(exchange=source.exchange),
            timeframe=DomainTimeframe(source.timeframe),
        )
        for source in candle_sources_qs
    ]

    async def cache_get_candles(
        prepared_domain: list[_PreparedSource],
    ) -> list[tuple[int, list[DomainCandle]]]:
        """Читает кэш для каждого источника. Возвращает list[(source_id, candles)]."""
        result: list[tuple[int, list[DomainCandle]]] = []
        for item in prepared_domain:
            cached = await cache.get_candles(
                exchange=item.exchange,
                trading_pair=item.trading_pair,
                timeframe=item.timeframe,
            )
            if cached:
                result.append((item.source_id, list(cached.values())))
        return result

    cache_results = asyncio.run(cache_get_candles(prepared_domain))

    candles = []
    synced_source_ids = []
    for source_id, domain_candles in cache_results:
        source = source_by_pk[source_id]
        synced_source_ids.append(source_id)
        for candle in domain_candles:
            candles.append(
                ExchangeCandle(
                    exchange=source.exchange,
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

    dispatch_traders_for_sources.delay(source_ids=synced_source_ids)
    dispatch_arbitrage_traders_for_sources.delay(source_ids=synced_source_ids)
