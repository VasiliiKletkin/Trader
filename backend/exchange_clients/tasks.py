import asyncio
from datetime import datetime
from typing import List

from celery import group, shared_task
from core.utils.types import Timeframe
from exchange_clients.domain.exchange_clients import Candle as DomainCandle
from exchange_clients.models import ExchangeClient, ExchangeClientCandleSource
from exchanges.models import Candle
from loguru import logger


async def fetch_candles_for_sources_async(
    exchange_client: ExchangeClient,
    sources: List[ExchangeClientCandleSource],
) -> List[Candle]:
    """Асинхронное получение свечей для списка источников."""
    client = exchange_client.instantiate()

    async with client:

        async def fetch_for_source(source: ExchangeClientCandleSource) -> List[Candle]:
            try:
                candles_raw: List[DomainCandle] = await client.get_candles(
                    trading_pair=source.trading_pair.symbol,
                    timeframe=Timeframe(source.timeframe).value,
                    limit=2,
                )
            except Exception as e:
                logger.error(
                    f"❌ Ошибка получения свечей для источника {source.pk}: {e}"
                )
                return []
            return [
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
                for c in candles_raw
            ]

        tasks = [fetch_for_source(source) for source in sources]
        results = await asyncio.gather(*tasks)
    return [candle for sublist in results for candle in sublist]


@shared_task(queue="fetch_last_candles")
def fetch_candles_for_exchange_client(exchange_client_id: int):
    """Celery задача для получения свечей для всех источников одного exchange_client."""
    try:
        exchange_client = ExchangeClient.active_objects.select_related("exchange").get(
            id=exchange_client_id
        )
        sources = ExchangeClientCandleSource.active_objects.filter(
            exchange_client=exchange_client,
        ).select_related("trading_pair")
    except ExchangeClient.DoesNotExist:
        logger.error(f"ExchangeClient с id {exchange_client_id} не существует.")
        return
    except ExchangeClientCandleSource.DoesNotExist:
        logger.error(
            f"Нет активных источников для exchange_client {exchange_client_id}."
        )
        return

    candles = asyncio.run(
        fetch_candles_for_sources_async(
            sources=list(sources),
            exchange_client=exchange_client,
        )
    )
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


@shared_task(queue="fetch_last_candles")
def sources_fetch_last_candles():
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


@shared_task
def fetch_candles_by_source(source_id: int, since: datetime):
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
