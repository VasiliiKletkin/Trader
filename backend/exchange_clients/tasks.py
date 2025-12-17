import asyncio
from collections import defaultdict
from datetime import datetime
import time
from typing import List, Optional

from celery import group, shared_task
from exchange_clients.domain import ExchangeClientBalance as DomainExchangeClientBalance
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClientBalance
from core.utils.types import TraderStatus
from django.db import models

from exchange_clients.domain import (
    ExchangeClientCandleSource as DomainExchangeClientCandleSource,
)
from exchange_clients.models import ExchangeClient, ExchangeClientCandleSource
from exchanges.domain import Candle as DomainCandle
from exchanges.models import ExchangeCandle
from loguru import logger
from traders.models import Trader
from traders.tasks import traders_process_for_exchange_client


@shared_task()
def exchange_client_candle_source_sync_candles(source_id: int, since: datetime):
    source = ExchangeClientCandleSource.objects.get(id=source_id)
    source.sync_candles(since=since)


@shared_task()
def sources_fetch_last_candles():
    exchange_clients_ids = ExchangeClientCandleSource.active_objects.values_list(
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

    candle_sources: models.QuerySet[ExchangeClientCandleSource] = (
        ExchangeClientCandleSource.active_objects.filter(
            exchange_client=exchange_client,
        )
        .select_related(
            "exchange_client",
            "trading_pair",
            "exchange_client__exchange",
        )
        .iterator()
    )

    logger.info(
        f"Найдено {len(candle_sources)} источников для exchange_client {exchange_client_id}"
    )

    domain_exchange_client = exchange_client.instantiate()
    tasks = [
        exchange_client_candle_source_pull_candles(
            source.instantiate(
                domain_exchange_client=domain_exchange_client,
            ),
            limit=2,
        )
        for source in candle_sources
    ]

    domain_candles: List[List[DomainCandle]] = asyncio.run(
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


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: List[asyncio.Task],
):
    async with exchange_client:
        return await asyncio.gather(*tasks)


async def exchange_client_candle_source_pull_candles(
    source: DomainExchangeClientCandleSource,
    limit: Optional[int] = None,
    since: Optional[datetime] = None,
) -> List[DomainCandle]:
    try:
        candles = await source.pull_candles(limit=limit, since=since)
        logger.info(f"Получено {len(candles)} свечей для источника {source}")
        return candles
    except Exception as e:
        logger.error(f"Ошибка при получении свечей для источника {source}: {e}")
        return []


def traders_process_by_sources(
    candle_sources: List[ExchangeClientCandleSource],
):
    traders: models.QuerySet[Trader] = (
        Trader.objects.filter(
            status__in=[
                TraderStatus.ENABLED,
                TraderStatus.PAUSED,
                TraderStatus.ERROR,
            ],
            candle_source__in=candle_sources,
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


@shared_task()
def exchange_clients_fetch_balances() -> None:
    time.sleep(20)

    exchange_clients: List[ExchangeClient] = list(
        ExchangeClient.active_objects.select_related("exchange", "proxy").all()
    )

    async def fetch_all_balances(exchange_clients: List[ExchangeClient]):
        tasks = [get_balances(client.instantiate()) for client in exchange_clients]
        return await asyncio.gather(*tasks)

    async def get_balances(
        exchange_client: DomainExchangeClient,
    ) -> List[DomainExchangeClientBalance]:
        async with exchange_client:
            return await exchange_client.get_balances()

    domain_balances = asyncio.run(fetch_all_balances(exchange_clients=exchange_clients))

    balances = [
        ExchangeClientBalance(
            exchange_client=exchange_client,
            currency=balance.currency,
            total=balance.total,
            debt=balance.debt,
            free=balance.free,
            used=balance.used,
        )
        for exchange_client, client_domain_balances in zip(
            exchange_clients, domain_balances
        )
        for balance in client_domain_balances
    ]

    if balances:
        ExchangeClientBalance.objects.bulk_create(
            balances,
            update_conflicts=True,
            update_fields=[
                "free",
                "used",
                "debt",
                "total",
                "updated_at",
            ],
            unique_fields=[
                "exchange_client",
                "currency",
            ],
        )
