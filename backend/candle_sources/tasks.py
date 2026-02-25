import asyncio
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

from celery import group, shared_task
from django.conf import settings
from django.db import models
from django.utils import timezone

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from arbitrage_traders.tasks import (
    arbitrage_traders_process_for_exchange_clients,
)
from candle_sources.models import (
    CandleSource,
    CandleSourceError,
    exchange_client_candle_source_fetch_candles,
    run_tasks_with_exchange_client,
)
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.models import ExchangeCandle
from telegram_bots.tasks import send_notification
from traders.models import Trader
from traders.schemas import TraderStatus
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

    candle_sources = CandleSource.active_objects.filter(
        exchange_client=exchange_client,
    ).select_related(
        "exchange_client",
        "trading_pair",
        "exchange_client__exchange",
    )

    tasks: list = []
    try:
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
                tasks=tasks,  # type: ignore[arg-type]
            )
        )
    except Exception as e:
        for task in tasks:
            task.close()
        CandleSourceError.objects.bulk_create(
            [
                CandleSourceError(
                    candle_source=source,
                    message=str(e),
                    type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
                for source in candle_sources
            ]
        )
        source_names = ", ".join(str(s) for s in candle_sources)
        send_notification.delay(
            message=(
                f"Ошибка загрузки свечей для источников: {source_names}\n"
                f"{type(e).__name__}: {e}"
            ),
        )
        return

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
        batch_size=settings.BULK_BATCH_SIZE,
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

    traders_process_by_sources(candle_sources=list(candle_sources))
    arbitrage_traders_process_by_sources(candle_sources=list(candle_sources))


def traders_process_by_sources(
    candle_sources: list[CandleSource],
):
    if not candle_sources:
        return

    traders = (
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

    traders_by_clients: dict[int, list[int]] = defaultdict(list)
    for trader in traders:
        traders_by_clients[trader.exchange_client.pk].append(trader.pk)

    if not traders_by_clients:
        return

    group(
        traders_process_for_exchange_client.s(
            exchange_client_id=exchange_client_id, traders_ids=traders_ids
        )
        for exchange_client_id, traders_ids in traders_by_clients.items()
    ).apply_async()


def arbitrage_traders_process_by_sources(
    candle_sources: list[CandleSource],
):
    if not candle_sources:
        return

    traders: models.QuerySet[ArbitrageTrader] = ArbitrageTrader.objects.filter(
        models.Q(left_candle_source__in=candle_sources)
        | models.Q(right_candle_source__in=candle_sources),
        status__in=[
            ArbitrageTraderStatus.ENABLED,
            ArbitrageTraderStatus.PAUSED,
            ArbitrageTraderStatus.ERROR,
        ],
    ).select_related(
        "left_candle_source",
        "right_candle_source",
        "left_exchange_client",
        "right_exchange_client",
    )

    # Проверяем что оба источника свечей синхронизированы в пределах 2 минут
    now = timezone.now()
    threshold = now - timedelta(minutes=2)

    ready_traders = [
        t
        for t in traders
        if t.left_candle_source.last_synced
        and t.right_candle_source.last_synced
        and t.left_candle_source.last_synced >= threshold
        and t.right_candle_source.last_synced >= threshold
    ]

    if not ready_traders:
        return

    # Группируем по паре (left_exchange_client, right_exchange_client)
    traders_by_clients: dict[tuple[int, int], list[int]] = defaultdict(list)
    for trader in ready_traders:
        key = (trader.left_exchange_client_id, trader.right_exchange_client_id)
        traders_by_clients[key].append(trader.pk)

    group(
        arbitrage_traders_process_for_exchange_clients.s(
            left_exchange_client_id=left_id,
            right_exchange_client_id=right_id,
            traders_ids=traders_ids,
        )
        for (left_id, right_id), traders_ids in traders_by_clients.items()
    ).apply_async()
