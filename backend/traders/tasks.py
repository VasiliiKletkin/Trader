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
        candles = source.fetch_candles(limit=2) # получаем последние 2 свечи

        if not candles:
            continue

        candle = candles[-2]
        traders: List[Trader] = source.traders.all()

        for trader in traders: # перебираем всех трейдеров, связанных с источником
            trader.data = trader.strategy.handle_candle(candle, trader.data)
            signal, trader.data = trader.strategy.get_signal(trader.data)

            price = candle.close

            trader.position_manager.check
            trader.check_positions(signal=signal, price=price)  # проверяем позиции трейдера

            opened_positions = trader.get_opened_positions()
            balance = trader.get_balance()
            if not trader.risk_manager.can_trade(
                signal=signal,
                price=price,
                balance=balance,
                opened_positions=opened_positions,
            ):
                continue

            stop_loss = trader.risk_manager.get_stop_loss(price)
            take_profit = trader.risk_manager.get_take_profit(price)
            position_size = trader.risk_manager.calculate_position_size(
                price=price,
                stop_loss=stop_loss,
                balance=balance,
            )

            if position_size <= 0:
                continue

            trader.create_order(
                signal=signal,
                price=price,
                volume=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
