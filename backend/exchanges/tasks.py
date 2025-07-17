from datetime import datetime

from celery import shared_task
from loguru import logger
from core.utils.types import Timeframe
from django.utils import timezone
from exchanges.models import CandleSource


@shared_task
def fetch_candles_by_source(candle_source_id: int, since: datetime):
    """
    Функция для асинхронного получения свечей для заданного источника.
    :param candle_source_id: ID источника свечей.
    :param since: Дата и время, с которых нужно начать получение свечей.
    """

    source = CandleSource.objects.get(id=candle_source_id)
    tf_enum = Timeframe(source.timeframe)
    default_count = 999
    step_delta = tf_enum.timedelta() * default_count

    now = timezone.now()
    if since > now:
        raise ValueError("The 'since' parameter cannot be in the future.")
    total_steps = ((now - since) // step_delta) + 1

    for step in range(total_steps):
        current_since = since + step * step_delta
        fetch_candles.delay(
            candle_source_id=candle_source_id,
            limit=default_count + 1,
            since=current_since,
        )


@shared_task
def fetch_candles(candle_source_id: int, limit: int, since: datetime) -> int:
    """
    Функция для получения свечей из источника.
    :param candle_source_id: ID источника свечей.
    :param limit: Максимальное количество свечей для получения.
    :param since: Дата и время, с которых нужно начать получение свечей.
    :return: Количество полученных свечей."""
    source = CandleSource.objects.get(id=candle_source_id)
    candles = source.fetch_candles(limit=limit, since=since)
    return len(candles)


@shared_task()  # Запуск каждую минуту
def sources_fetch_last_candles():
    """Получение свечей для всех активных источников."""
    sources = CandleSource.active_objects.all()
    for source in sources.iterator():
        source_fetch_last_candles.delay(source_id=source.pk)


@shared_task()
def source_fetch_last_candles(source_id: int):
    """Получение свечей для конкретного источника."""
    try:
        source = CandleSource.objects.get(id=source_id)
    except CandleSource.DoesNotExist:
        logger.error(f"CandleSource with id {source_id} does not exist.")
        return
    source.fetch_candles(limit=2)
