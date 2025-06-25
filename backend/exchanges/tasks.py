from datetime import datetime
from django.utils import timezone
from typing import List

from celery import shared_task
from core.utils.types import Timeframe
from exchanges.models import CandleSource


@shared_task
def save_all_candles_by_candle_source(timeframe: str):
    tf_enum = Timeframe(timeframe)
    sources: List[CandleSource] = CandleSource.active_objects.select_related(
        "exchange", "trading_pair"
    ).filter(timeframe=tf_enum.value)

    for source in sources:
        source.fetch_candles(limit=3)


@shared_task
def fetch_candles(candle_source_id: int, since: datetime) -> int:
    """
    Функция для асинхронного получения свечей для заданного источника.
    :param candle_source_id: ID источника свечей.
    :param since: Дата и время, с которых нужно начать получение свечей.
    """

    source = CandleSource.objects.get(id=candle_source_id)
    tf_enum = Timeframe(source.timeframe)
    default_count = 1000
    step_delta = tf_enum.timedelta() * default_count

    now = timezone.now()
    if since > now:
        raise ValueError("The 'since' parameter cannot be in the future.")
    total_steps = ((now - since) // step_delta) + 1

    total_saved = 0
    for step in range(total_steps):
        current_since = since + step * step_delta
        candles = source.fetch_candles(limit=default_count, since=current_since)
        total_saved += len(candles)
    return total_saved
