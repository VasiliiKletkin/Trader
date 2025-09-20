import asyncio
from datetime import datetime
from typing import Dict, List

from celery import group, shared_task
from django.db import models
from exchange_clients.domain import (
    AbstractExchangeClient as DomainAbstractExchangeClient,
)
from exchange_clients.domain import (
    ExchangeClientCandleSource as DomainExchangeClientCandleSource,
)
from exchange_clients.domain.exchange_clients import Candle as DomainCandle
from exchange_clients.models import ExchangeClient, ExchangeClientCandleSource
from exchanges.models import Candle
from loguru import logger
from traders.tasks import handle_candle_by_sources


@shared_task(queue="fetch_last_candles")
def fetch_last_candles():
    """Главная задача: получение свечей для всех уникальных exchange_clients через подзадачи."""
    exchange_clients_ids = ExchangeClientCandleSource.active_objects.values_list(
        "exchange_client_id", flat=True
    ).distinct()

    if not exchange_clients_ids:
        logger.info("Нет активных источников.")
        return

    task_group = group(
        fetch_candles_for_exchange_client.s(client_id)
        for client_id in exchange_clients_ids
    )
    task_group.apply_async()
    logger.info(
        f"🚀 Запущено {len(exchange_clients_ids)} подзадач для exchange_clients"
    )


@shared_task(queue="fetch_last_candles")
def fetch_candles_for_exchange_client(exchange_client_id: int):
    """Celery задача для получения свечей для всех источников одного exchange_client."""

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)

    sources: List[ExchangeClientCandleSource] = (
        ExchangeClientCandleSource.active_objects.filter(
            exchange_client=exchange_client,
        ).select_related("trading_pair")
    )

    domain_exchange_client = exchange_client.instantiate()

    tasks = []
    for source in sources:
        domain_source = source.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        tasks.append(fetch_for_source(source=domain_source))

    domain_candles = asyncio.run(
        run_tasks(
            exchange_client=domain_exchange_client,
            tasks=tasks,
        )
    )

    candles = [
        Candle(
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
        for source, sub_candles in zip(sources, domain_candles)
        for c in sub_candles
    ]

    if candles:
        Candle.objects.bulk_create(
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
    handle_candle_by_sources.delay(sources_ids=[s.pk for s in sources])


async def run_tasks(
    exchange_client: DomainAbstractExchangeClient,
    tasks: List,
) -> List[List[DomainCandle]]:
    async with exchange_client:
        return await asyncio.gather(*tasks)


async def fetch_for_source(
    source: DomainExchangeClientCandleSource,
) -> List[DomainCandle]:
    return await source.get_candles(limit=2)


@shared_task(queue="source_fetch_candles")
def source_fetch_candles(source_id: int, since: datetime):
    """
    Функция для асинхронного получения свечей для заданного источника.
    :param source_id: ID источника свечей.
    :param since: Дата и время, с которых нужно начать получение свечей.
    """
    try:
        source = ExchangeClientCandleSource.objects.get(id=source_id)
    except ExchangeClientCandleSource.DoesNotExist:
        logger.error(f"ExchangeClientCandleSource с id {source_id} не существует.")
        return
    source.fetch_candles(since=since)
