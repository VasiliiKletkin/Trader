from typing import List

from celery import shared_task
from core.utils.types import SignalType, Timeframe
from exchanges.models import CandleSource, ExchangeClient
from traders.models import Trader


@shared_task
def trade_loop(timeframe: str):

    tf = Timeframe(timeframe)
    sources: List[CandleSource] = CandleSource.active_objects.select_related(
        "exchange_client",
    ).filter(timeframe=tf)

    clients = ExchangeClient.objects.filter(candle_sources__in=sources)

    for client in clients:  # получаем все данные по клиентам
        client.fetch_orders()

    for source in sources:
        candles = source.fetch_candles(limit=2)  # получаем последние 2 свечи

        if not candles:
            continue

        candle = candles[-2]
        traders: List[Trader] = source.traders.all()

        for trader in traders:
            trader.trade(candle=candle)
