from typing import List

from celery import shared_task
from core.utils.types import SignalType, Timeframe
from exchanges.models import CandleSource
from traders.models import Trader


@shared_task
def trade_loop(timeframe: str):
    tf = Timeframe(timeframe)
    sources: List[CandleSource] = CandleSource.active_objects.select_related(
        "exchange_client",
    ).filter(timeframe=tf)

    for source in sources:
        candle = source.fetch_candles(limit=2)[0]
        traders: List[Trader] = source.traders.all()
        for trader in traders:
            trader.handle_candle(candle)
            signal = trader.get_signal()
            if signal == SignalType.HOLD:
                continue
            # trader.create_order(
            #     signal,
            #     candle.close,
            # )
