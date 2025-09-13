from celery import shared_task
from core.utils.celery import run_tasks_in_groups
from core.utils.types import Timeframe, TraderStatus
from loguru import logger
from django.utils import timezone
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
    trader_ids = list(
        Trader.objects.filter(status=TraderStatus.ENABLED).values_list("pk", flat=True)
    )
    task_params = [{'trader_id': trader_id} for trader_id in trader_ids]
    run_tasks_in_groups(trader_check_opened_positions, task_params, chunk_size=20)


@shared_task()
def trader_check_opened_positions(trader_id: int):
    try:
        trader = Trader.objects.select_related(
            "exchange_client",
            "trading_pair",
        ).get(id=trader_id)
        candle = trader.candles.order_by("-timestamp").first()
        if candle is None:
            logger.warning(f"No candles found for trader {trader.pk}")
            return
        trader.check_opened_positions(candle=candle)
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")
    except Exception as e:
        logger.error(f"Error checking opened positions for trader {trader_id}: {e}")


@shared_task()
def traders_handle_candle(timeframe: str):
    """
    Функция для запуска торгового цикла для всех трейдеров
    на заданном таймфрейме.
    """
    tf = Timeframe(timeframe)
    trader_ids = list(
        Trader.objects.filter(timeframe=tf, status=TraderStatus.ENABLED).values_list(
            "pk", flat=True
        )
    )
    task_params = [{'trader_id': trader_id} for trader_id in trader_ids]
    run_tasks_in_groups(trader_handle_candle, task_params, chunk_size=20)


@shared_task()
def trader_handle_candle(trader_id: int):
    try:
        trader = Trader.objects.select_related(
            "exchange_client",
            "trading_pair",
            "strategy",
            "risk_manager",
        ).get(id=trader_id)
        now = timezone.now()
        tf_timedelta = Timeframe(trader.timeframe).timedelta()
        candle = trader.get_candle_at_time(now - tf_timedelta)
        if candle is None:
            logger.warning(f"Unable to get candle for trader {trader.pk}")
            return
        trader.handle_candle(candle=candle)
    except Trader.DoesNotExist:
        logger.error(f"Trader with id {trader_id} does not exist.")
    except Exception as e:
        logger.error(f"Error handling candle for trader {trader_id}: {e}")
