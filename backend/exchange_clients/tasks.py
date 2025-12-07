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
from exchanges.models import Candle
from loguru import logger
from traders.models import Trader
from traders.tasks import traders_process_for_exchange_client


@shared_task()
def source_fetch_candles(source_id: int, since: datetime):
    logger.info(f"Начало получения свечей для источника {source_id} с {since}")
    try:
        source = ExchangeClientCandleSource.objects.get(id=source_id)
        source.fetch_candles(since=since)
        logger.info(f"Завершено получение свечей для источника {source_id}")
    except ExchangeClientCandleSource.DoesNotExist:
        logger.error(f"ExchangeClientCandleSource с id {source_id} не существует.")


@shared_task()
def sources_fetch_last_candles():
    logger.info("Начало главной задачи sources_fetch_last_candles")
    exchange_clients_ids = ExchangeClientCandleSource.active_objects.values_list(
        "exchange_client_id", flat=True
    ).distinct()

    if not exchange_clients_ids:
        logger.info("Нет активных источников.")
        return

    group(
        sources_fetch_last_candles_for_exchange_client.s(exchange_client_id=client_id)
        for client_id in exchange_clients_ids
    ).apply_async()

    logger.info(
        f"🚀 Запущено {len(exchange_clients_ids)} подзадач для exchange_clients"
    )


@shared_task(queue="sources_fetch_last_candles_for_exchange_client")
def sources_fetch_last_candles_for_exchange_client(exchange_client_id: int):
    logger.info(f"Начало получения свечей для exchange_client {exchange_client_id}")

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)
    sources: List[
        ExchangeClientCandleSource
    ] = ExchangeClientCandleSource.active_objects.filter(
        exchange_client=exchange_client,
    ).select_related(
        "exchange_client",
        "trading_pair",
        "exchange_client__exchange",
    )
    logger.info(
        f"Найдено {len(sources)} источников для exchange_client {exchange_client_id}"
    )

    domain_exchange_client = exchange_client.instantiate()
    tasks = [
        source_get_candles(
            source.instantiate(
                domain_exchange_client=domain_exchange_client,
            ),
            limit=2,
        )
        for source in sources
    ]

    domain_candles: List[List[DomainCandle]] = asyncio.run(
        run_tasks_with_exchange_client(
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
        logger.info(
            f"Сохранено {len(candles)} свечей для exchange_client {exchange_client_id}"
        )
        traders_process_by_sources_send_tasks(sources=sources)
    else:
        logger.info(
            f"Нет новых свечей для сохранения для exchange_client {exchange_client_id}"
        )

    logger.info(f"Завершено получение свечей для exchange_client {exchange_client_id}")


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: List[asyncio.Task],
):
    async with exchange_client:
        return await asyncio.gather(*tasks)


async def source_get_candles(
    source: DomainExchangeClientCandleSource,
    limit: Optional[int] = None,
    since: Optional[datetime] = None,
) -> List[DomainCandle]:
    logger.info(f"Начало получения свечей для источника {source}")
    try:
        candles = await source.get_candles(limit=limit, since=since)
        logger.info(f"Получено {len(candles)} свечей для источника {source}")
        return candles
    except Exception as e:
        logger.error(f"Ошибка при получении свечей для источника {source}: {e}")
        return []


def traders_process_by_sources_send_tasks(
    sources: models.QuerySet[ExchangeClientCandleSource],
):
    logger.info(f"Начало построения фильтра для {len(sources)} источников")
    traders_filter = models.Q()
    for source in sources:
        traders_filter |= models.Q(
            exchange_client__exchange=source.exchange_client.exchange,
            trading_pair=source.trading_pair,
            timeframe=source.timeframe,
        )
    traders_filter &= models.Q(
        status__in=[
            TraderStatus.ENABLED,
            TraderStatus.PAUSED,
            TraderStatus.ERROR,
        ]
    )

    traders = Trader.objects.filter(traders_filter).select_related(
        "exchange_client", "exchange_client__exchange", "candle_source__trading_pair"
    )
    logger.info(f"Найдено {len(traders)} активных трейдеров")

    traders_by_clients = defaultdict(list)
    for trader in traders:
        traders_by_clients[trader.exchange_client.pk].append(trader.pk)

    group(
        traders_process_for_exchange_client.s(
            exchange_client_id=exchange_client_id, traders_ids=traders_ids
        )
        for exchange_client_id, traders_ids in traders_by_clients.items()
    ).apply_async()
    logger.info(f"Запущено {len(traders_by_clients)} подзадач для exchange_clients")


@shared_task()
def exchange_clients_fetch_balances() -> None:
    time.sleep(20)
    exchange_clients: List[ExchangeClient] = ExchangeClient.active_objects.all()

    async def fetch_all_balances(clients: List[ExchangeClient]):
        tasks = [get_balances(client.instantiate()) for client in clients]
        return await asyncio.gather(*tasks)

    async def get_balances(
        client: DomainExchangeClient,
    ) -> List[DomainExchangeClientBalance]:
        async with client:
            return await client.get_balances()

    domain_balances = asyncio.run(fetch_all_balances(exchange_clients))

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
