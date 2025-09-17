import asyncio
from datetime import datetime
from typing import List

from celery import shared_task
from core.utils.types import Timeframe
from django.db import models
from exchange_clients.domain.exchange_clients import Candle as DomainCandle
from exchange_clients.models import ExchangeClientCandleSource
from exchanges.models import Candle
from loguru import logger


async def sources_fetch_last_candles_async(
    sources: List[ExchangeClientCandleSource],
) -> List[Candle]:
    """Асинхронное получение свечей для всех источников."""
    semaphore = asyncio.Semaphore(10)

    async def source_fetch_last_candles_async(
        source: ExchangeClientCandleSource,
    ) -> List[Candle]:
        """Получить свечи для одного источника."""
        async with semaphore:
            exchange_client = source.exchange_client.instantiate()
            try:
                async with exchange_client:
                    candles_raw: List[DomainCandle] = await exchange_client.get_candles(
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

    tasks = [source_fetch_last_candles_async(source) for source in sources]
    results = await asyncio.gather(*tasks)
    return [candle for sublist in results for candle in sublist]


@shared_task(queue="fetch_last_candles")
def sources_fetch_last_candles():
    """Получение свечей для всех активных источников."""
    sources: models.QuerySet[ExchangeClientCandleSource] = (
        ExchangeClientCandleSource.active_objects.prefetch_related(
            "exchange_client", "trading_pair"
        ).all()
    )

    all_candles = asyncio.run(sources_fetch_last_candles_async(list(sources)))
    Candle.objects.bulk_create(
        all_candles,
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
