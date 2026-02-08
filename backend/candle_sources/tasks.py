import asyncio
from collections import defaultdict
from datetime import datetime

from celery import group, shared_task
from django.db import models

from candle_sources.models import (
    CandleSource,
    exchange_client_candle_source_fetch_candles,
    run_tasks_with_exchange_client,
)
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.models import ExchangeCandle
from traders.models import Trader
from traders.tasks import traders_process_for_exchange_client


@shared_task()
def exchange_client_candle_source_sync_candles(source_id: int, since: datetime):
    source = CandleSource.objects.get(id=source_id)
    source.sync_candles(since=since)


@shared_task()
def sources_fetch_last_candles():
    exchange_clients_ids = CandleSource.active_objects.values_list(
        "exchange_client_id", flat=True
    ).distinct()
    group(
        sources_fetch_last_candles_for_exchange_client.s(exchange_client_id=client_id)
        for client_id in exchange_clients_ids
    ).apply_async()


@shared_task(queue="sources_fetch_last_candles_for_exchange_client")
def sources_fetch_last_candles_for_exchange_client(exchange_client_id: int):
    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)

    candle_sources: list[CandleSource] = CandleSource.active_objects.filter(
        exchange_client=exchange_client,
    ).select_related(
        "exchange_client",
        "trading_pair",
        "exchange_client__exchange",
    )

    domain_exchange_client = exchange_client.instantiate()
    tasks = [
        exchange_client_candle_source_fetch_candles(
            source.instantiate(
                domain_exchange_client=domain_exchange_client,
            ),
            limit=2,
        )
        for source in candle_sources
    ]

    domain_candles: list[list[DomainCandle]] = asyncio.run(
        run_tasks_with_exchange_client(
            exchange_client=domain_exchange_client,
            tasks=tasks,
        )
    )

    candles = [
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
        for source, sub_candles in zip(candle_sources, domain_candles)
        for c in sub_candles
    ]

    ExchangeCandle.objects.bulk_create(
        candles,
        update_conflicts=True,
        update_fields=[
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
        unique_fields=[
            "exchange",
            "timeframe",
            "trading_pair",
            "timestamp",
        ],
    )

    traders_process_by_sources(candle_sources=candle_sources)


def traders_process_by_sources(
    candle_sources: list[CandleSource],
):
    from core.utils.types import TraderStatus

    if not candle_sources:
        return

    traders: models.QuerySet[Trader] = (
        Trader.objects.filter(
            candle_source__in=candle_sources,
            status__in=[
                TraderStatus.ENABLED,
                TraderStatus.PAUSED,
                TraderStatus.ERROR,
            ],
        )
        .select_related(
            "exchange_client",
        )
        .iterator()
    )

    traders_by_clients = defaultdict(list)
    for trader in traders:
        traders_by_clients[trader.exchange_client.pk].append(trader.pk)

    if traders_by_clients:
        group(
            traders_process_for_exchange_client.s(
                exchange_client_id=exchange_client_id, traders_ids=traders_ids
            )
            for exchange_client_id, traders_ids in traders_by_clients.items()
        ).apply_async()
