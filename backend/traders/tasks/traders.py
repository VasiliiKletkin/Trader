import asyncio
from decimal import Decimal

from celery import group, shared_task
from django.db import models
from django.utils import timezone

from core.utils.common import dt_str, format_fee, format_pnl
from telegram_bots.tasks import send_notification
from traders.models import Trader, TraderError, TraderOrder
from traders.schemas import PositionStatus, TraderStatus


@shared_task()
def dispatch_traders_for_sources(source_ids: list[int]):
    """Находит трейдеров по источникам свечей и запускает обработку."""
    traders_ids = list(
        Trader.objects.filter(
            candle_source_id__in=source_ids,
            status__in=[
                TraderStatus.ENABLED,
                TraderStatus.PAUSED,
                TraderStatus.ERROR,
            ],
        ).values_list("id", flat=True)
    )

    if not traders_ids:
        return

    tasks = group(trader_process.s(trader_id=tid) for tid in traders_ids)
    tasks.apply_async()


@shared_task()
def trader_process(trader_id: int) -> None:
    """Обработка одной свечи для конкретного трейдера."""

    trader = Trader.objects.select_related(
        "exchange_client",
        "exchange_client__exchange",
        "exchange_client__proxy",
        "candle_source",
        "candle_source__trading_pair",
        "candle_source__exchange",
        "risk_manager",
        "strategy",
    ).get(id=trader_id)

    try:
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        last_candle = trader.get_last_candle()
        if last_candle:
            asyncio.run(domain_trader.handle_candle(candle=last_candle.instantiate()))
        trader.sync(trader=domain_trader)
    except Exception as e:
        TraderError.objects.create(
            trader=trader,
            message=str(e),
            type=type(e).__name__,
        )
        send_notification.delay(
            message=(f"Ошибка обработки трейдера: {trader}\n[{type(e).__name__}]: {e}"),
        )


@shared_task(queue="trader")
def traders_daily_report():
    end_date = timezone.now()
    start_date = end_date - timezone.timedelta(days=1)

    result = TraderOrder.objects.filter(
        position__status=PositionStatus.CLOSED,
        position__closed_at__gte=start_date,
        position__closed_at__lt=end_date,
    ).aggregate(
        pnl=models.Sum(Trader.fact_pnl_annotation(), default=Decimal("0.00")),
        fee=models.Sum("order__fee", default=Decimal("0.00")),
    )

    pnl = format_pnl(result["pnl"])
    fee = format_fee(result["fee"])

    send_notification.delay(
        message=(
            f"Ежедневный отчет по трейдерам за период "
            f"с {dt_str(start_date)} по {dt_str(end_date)}:\n"
            f"Общий PnL: {pnl}\n"
            f"Общие комиссии: {fee}\n"
        )
    )


@shared_task(queue="trader")
def trader_reboot(trader_id: int):
    """
    Перезагружает трейдера с историческими данными.
    """
    trader = Trader.objects.select_related(
        "exchange_client",
        "exchange_client__exchange",
        "exchange_client__proxy",
        "candle_source",
        "candle_source__trading_pair",
        "candle_source__exchange",
        "risk_manager",
        "strategy",
    ).get(id=trader_id)
    trader.reboot()


@shared_task(queue="trader")
def trader_clear_all_data(trader_id: int):
    """Очистить все данные трейдера: сигналы, позиции, ордера, ошибки."""
    trader = Trader.objects.get(id=trader_id)
    trader.clear_all_data()


@shared_task(queue="trader")
def trader_clear_all_errors(trader_id: int):
    """Удалить все ошибки трейдера."""
    trader = Trader.objects.get(id=trader_id)
    trader.clear_all_errors()
