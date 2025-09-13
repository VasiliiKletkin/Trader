from datetime import datetime

from celery import shared_task
from core.utils.celery import run_tasks_in_groups
from loguru import logger
from exchange_clients.models import ExchangeClientCandleSource
from core.utils.types import Timeframe
from django.utils import timezone


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

    tf_enum = Timeframe(source.timeframe)
    default_count = 999
    step_delta = tf_enum.timedelta() * default_count

    now = timezone.now()
    if since > now:
        raise ValueError("Since не может быть в будущем.")
    total_steps = ((now - since) // step_delta) + 1

    task_params = [
        {
            "candle_source_id": source_id,
            "limit": default_count + 1,
            "since": since + step * step_delta,
        }
        for step in range(total_steps)
    ]
    run_tasks_in_groups(fetch_candles, task_params, chunk_size=20)


@shared_task
def fetch_candles(candle_source_id: int, limit: int, since: datetime) -> int:
    """
    Функция для получения свечей из источника.
    :param candle_source_id: ID источника свечей.
    :param limit: Максимальное количество свечей для получения.
    :param since: Дата и время, с которых нужно начать получение свечей.
    :return: Количество полученных свечей.
    """
    source = ExchangeClientCandleSource.objects.get(id=candle_source_id)
    candles = source.fetch_candles(limit=limit, since=since)
    return len(candles)


@shared_task()  # Запуск каждую минуту
def sources_fetch_last_candles():
    """Получение свечей для всех активных источников."""
    sources = list(
        ExchangeClientCandleSource.active_objects.values_list("pk", flat=True)
    )
    task_params = [{"source_id": source_id} for source_id in sources]
    run_tasks_in_groups(source_fetch_last_candles, task_params, chunk_size=20)


@shared_task()
def source_fetch_last_candles(source_id: int):
    """Получение свечей для конкретного источника."""
    try:
        source = ExchangeClientCandleSource.objects.get(id=source_id)
    except ExchangeClientCandleSource.DoesNotExist:
        logger.error(f"ExchangeClientCandleSource с id {source_id} не существует.")
        return
    source.fetch_candles(limit=2)
