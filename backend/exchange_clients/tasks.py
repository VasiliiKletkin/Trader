from datetime import datetime

from celery import shared_task
from core.utils.celery import run_tasks_in_groups
from loguru import logger
from exchange_clients.models import ExchangeClientCandleSource


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
