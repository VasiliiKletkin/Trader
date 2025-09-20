import asyncio
from datetime import datetime
from typing import List

from celery import group, shared_task
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
from traders.tasks import traders_process_by_sources


@shared_task(queue="source_fetch_candles")
def source_fetch_candles(source_id: int, since: datetime):
    """
    Функция для асинхронного получения свечей для заданного источника.
    :param source_id: ID источника свечей.
    :param since: Дата и время, с которых нужно начать получение свечей.
    """
    logger.info(f"Начало получения свечей для источника {source_id} с {since}")
    try:
        source = ExchangeClientCandleSource.objects.get(id=source_id)
    except ExchangeClientCandleSource.DoesNotExist:
        logger.error(f"ExchangeClientCandleSource с id {source_id} не существует.")
        return
    source.fetch_candles(since=since)
    logger.info(f"Завершено получение свечей для источника {source_id}")


@shared_task(queue="fetch_last_candles")
def fetch_last_candles():
    """Главная задача: получение свечей для всех уникальных exchange_clients через подзадачи."""
    logger.info("Начало главной задачи fetch_last_candles")
    exchange_clients_ids = ExchangeClientCandleSource.active_objects.values_list(
        "exchange_client_id", flat=True
    ).distinct()

    if not exchange_clients_ids:
        logger.info("Нет активных источников.")
        return

    task_group = group(
        fetch_candles_for_exchange_client.s(exchange_client_id=client_id)
        for client_id in exchange_clients_ids
    )
    task_group.apply_async()
    logger.info(
        f"🚀 Запущено {len(exchange_clients_ids)} подзадач для exchange_clients"
    )


@shared_task(queue="fetch_last_candles")
def fetch_candles_for_exchange_client(exchange_client_id: int):
    """Celery задача для получения свечей для всех источников одного exchange_client."""
    logger.info(f"Начало получения свечей для exchange_client {exchange_client_id}")

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)

    sources: List[ExchangeClientCandleSource] = (
        ExchangeClientCandleSource.active_objects.filter(
            exchange_client=exchange_client,
        ).select_related("trading_pair")
    )
    logger.info(
        f"Найдено {len(sources)} источников для exchange_client {exchange_client_id}"
    )

    domain_exchange_client = exchange_client.instantiate()

    tasks = []
    for source in sources:
        domain_source = source.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        tasks.append(fetch_for_source(source=domain_source))

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
    else:
        logger.info(
            f"Нет новых свечей для сохранения для exchange_client {exchange_client_id}"
        )

    traders_process_by_sources.delay(sources_ids=[s.pk for s in sources])
    logger.info(f"Завершено получение свечей для exchange_client {exchange_client_id}")


async def run_tasks_with_exchange_client(
    exchange_client: DomainAbstractExchangeClient,
    tasks: List[asyncio.Task],
):
    async with exchange_client:
        return await asyncio.gather(*tasks)


async def fetch_for_source(
    source: DomainExchangeClientCandleSource,
) -> List[DomainCandle]:
    logger.info(f"Начало получения свечей для источника {source}")
    try:
        candles = await source.get_candles(limit=2)
    except Exception as e:
        logger.error(f"Ошибка при получении свечей для источника {source}: {e}")
        return []
    logger.info(f"Получено {len(candles)} свечей для источника {source}")
    return candles
