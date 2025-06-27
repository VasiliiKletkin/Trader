from typing import List

from celery import shared_task
from core.utils.types import Timeframe
from exchanges.models import CandleSource, ExchangeClient
from traders.models import Trader


@shared_task(queue="trade_loop")
def trade_loop(timeframe: str):

    tf = Timeframe(timeframe)
    sources: List[CandleSource] = CandleSource.active_objects.select_related(
        "exchange_client",
    ).filter(timeframe=tf)

    for source in sources:
        candles = source.fetch_candles(limit=2)

        if not candles:
            continue

        candle = candles[-2]
        traders: List[Trader] = source.traders.all()

        for trader in traders:
            trader.trade(candle=candle)


@shared_task
def reboot_trader(trader_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
        trader.reboot()
    except Trader.DoesNotExist:
        return f"Trader with id {trader_id} does not exist."
    return f"Trader with id {trader_id} has been rebooted successfully."
