from typing import List

from celery import shared_task
from django.utils import timezone
from exchanges.models import CandleSource as CandleSourceModel
from exchanges.models import Timeframe as TimeframeModel
from django.db.models import QuerySet
from traders.models import Trader as TraderModel


@shared_task
def trade_loop(timeframe: str):
    tf_enum = TimeframeModel(timeframe)
    sources: List[CandleSourceModel] = CandleSourceModel.active_objects.select_related(
        "exchange", "trading_pair"
    ).filter(timeframe=tf_enum.value)

    for source in sources:
        new_candles = source.save_candles(limit=2)
        traders: List[TraderModel] = source.traders.all()
        for trader in traders:
            trader.handle_candle(new_candles[0])
