from celery import shared_task
from loguru import logger
from core.utils.types import Timeframe, TraderStatus
from exchanges.models import Candle, CandleSource
from traders.models import Trader


@shared_task
def trader_reboot(trader_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
        trader.reboot()
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")


@shared_task()  # Запуск каждую минуту
def traders_control_close_positions():
    """Контроль открытых позиций для всех активных трейдеров."""
    traders = Trader.objects.filter(status=TraderStatus.ENABLED)
    for trader in traders.iterator():
        trader_control_close_positions.delay(trader_id=trader.pk)


@shared_task()
def trader_control_close_positions(trader_id: int):
    """Контроль открытых позиций для конкретного трейдера."""
    try:
        trader = Trader.objects.get(id=trader_id)
        candle = trader.candles.latest("timestamp")
        if candle is None:
            logger.warning(f"No candles found for trader {trader.pk}")
            return
        trader.control_close_positions(candle=candle)
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")


@shared_task()
def traders_control_open_positions(timeframe: str):
    """Функция для запуска торгового цикла для всех трейдеров на заданном таймфрейме."""
    tf = Timeframe(timeframe)
    traders = Trader.objects.filter(timeframe=tf, status=TraderStatus.ENABLED)
    for trader in traders.iterator():
        trader_control_open_positions.delay(trader.pk)


@shared_task()
def trader_control_open_positions(trader_id: int):
    """Функция для выполнения торгового цикла для конкретного трейдера."""
    try:
        trader = Trader.objects.get(id=trader_id)
        candle = trader.candles.latest("timestamp")
        if candle is None:
            logger.warning(f"No candles found for trader {trader.pk}")
            return
        trader.control_open_positions(candle=candle)
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")


# @shared_task()
# def trader_trade(trader_id: int, candle_id: int):
#     try:
#         trader = Trader.objects.get(id=trader_id)
#         candle = Candle.objects.get(id=candle_id)
#         trader.trade(candle=candle)
#     except (Trader.DoesNotExist, CandleSource.DoesNotExist):
#         logger.error(
#             f"Trader with id {trader_id} or Candle with id {candle_id} does not exist."
#         )
