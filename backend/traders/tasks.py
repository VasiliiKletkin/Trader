from celery import shared_task
from core.utils.types import Timeframe, TraderStatus
from loguru import logger
from traders.models import Trader


@shared_task(queue="trader_reboot")
def trader_reboot(trader_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
        trader.reboot()
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")


@shared_task()
def traders_check_opened_positions():
    """Контроль открытых позиций для всех активных трейдеров."""
    traders = Trader.objects.filter(status=TraderStatus.ENABLED)
    for trader in traders.iterator():
        trader_check_opened_positions.delay(trader_id=trader.pk)


@shared_task()
def trader_check_opened_positions(trader_id: int):
    """Контроль открытых позиций для конкретного трейдера."""
    try:
        trader = Trader.objects.get(id=trader_id)
        candle = trader.candles.latest("timestamp")
        if candle is None:
            logger.warning(f"No candles found for trader {trader.pk}")
            return
        trader.check_opened_positions(candle=candle)
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")


@shared_task()
def traders_handle_candle(timeframe: str):
    """Функция для запуска торгового цикла для всех трейдеров на заданном таймфрейме."""
    tf = Timeframe(timeframe)
    traders = Trader.objects.filter(timeframe=tf, status=TraderStatus.ENABLED)
    for trader in traders.iterator():
        trader_handle_candle.delay(trader.pk)


@shared_task()
def trader_handle_candle(trader_id: int):
    """Функция для выполнения торгового цикла для конкретного трейдера."""
    try:
        trader = Trader.objects.get(id=trader_id)
        candle = trader.candles.latest("timestamp")
        if candle is None:
            logger.warning(f"No candles found for trader {trader.pk}")
            return
        trader.handle_candle(candle=candle)
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")
