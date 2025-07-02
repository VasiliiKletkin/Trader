from typing import List

from celery import shared_task
from core.utils.types import Timeframe
from exchanges.models import CandleSource
from traders.models import Trader


@shared_task(queue="trade_loop")
def trade_loop(timeframe: str):
    tf = Timeframe(timeframe)
    sources: List[CandleSource] = CandleSource.active_objects.select_related(
        "exchange_client",
    ).filter(timeframe=tf)

    for source in sources:
        trade_loop_source.delay(source_id=source.pk)


@shared_task(queue="trade_loop")
def trade_loop_source(source_id: int):
    source = CandleSource.objects.get(id=source_id)
    candles = source.fetch_candles(limit=2)

    if not candles:
        return

    candle = candles[-2]
    traders: List[Trader] = source.enabled_traders.all()

    for trader in traders:
        trader.trade(candle=candle)


@shared_task
def trader_reboot(trader_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
        trader.reboot()
    except Trader.DoesNotExist:
        return f"Trader with id {trader_id} does not exist."
    return f"Trader with id {trader_id} has been rebooted successfully."
