from celery import shared_task
from loguru import logger
from core.utils.types import Timeframe
from exchanges.models import Candle, CandleSource
from traders.models import Trader
from django.db import models


@shared_task(queue="trade_loop")
def trade_loop(timeframe: str):
    tf = Timeframe(timeframe)
    sources: models.QuerySet[CandleSource] = CandleSource.active_objects.filter(
        timeframe=tf
    )
    for source in sources.iterator():
        trade_loop_source.delay(source_id=source.pk)


@shared_task(queue="trade_loop")
def trade_loop_source(source_id: int):
    source = CandleSource.objects.get(id=source_id)
    candles = source.fetch_candles(limit=2)

    if not candles:
        return

    candle = candles[-2]
    traders: models.QuerySet[Trader] = source.enabled_traders.all()

    for trader in traders.iterator():
        trader_trade.delay(trader_id=trader.pk, candle_id=candle.pk)


@shared_task(queue="trade_loop")
def trader_trade(trader_id: int, candle_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
        candle = Candle.objects.get(id=candle_id)
        trader.trade(candle=candle)
    except (Trader.DoesNotExist, CandleSource.DoesNotExist):
        logger.error(
            f"Trader with id {trader_id} or Candle with id {candle_id} does not exist."
        )


@shared_task
def trader_reboot(trader_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
        trader.reboot()
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")
