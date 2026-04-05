import asyncio
from decimal import Decimal

from celery import shared_task
from django.db import models
from django.utils import timezone

from core.utils.common import dt_str
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
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

    traders_process.delay(traders_ids=traders_ids)


@shared_task()
def traders_process(traders_ids: list[int]) -> None:
    """Обработка свечи для всех трейдеров из списка."""
    traders = Trader.objects.select_related(
        "exchange_client",
        "exchange_client__exchange",
        "exchange_client__proxy",
        "candle_source",
        "candle_source__trading_pair",
        "candle_source__exchange_client",
        "candle_source__exchange_client__exchange",
        "risk_manager",
        "strategy",
    ).filter(
        id__in=traders_ids,
        status__in=[
            TraderStatus.ENABLED,
            TraderStatus.PAUSED,
            TraderStatus.ERROR,
        ],
    )

    for trader in traders:
        try:
            domain_trader = trader.instantiate()
            trader.load(trader=domain_trader)
            last_candle = trader.get_last_candle()
            if last_candle:
                asyncio.run(
                    trader_handle_candle_async(
                        trader=domain_trader,
                        candle=last_candle.instantiate(),
                    )
                )
            trader.sync(trader=domain_trader)
        except Exception as e:
            TraderError.objects.create(
                trader=trader,
                message=str(e),
                type=type(e).__name__,
            )
            send_notification.delay(
                message=(
                    f"Ошибка обработки трейдера: {trader}\n[{type(e).__name__}]: {e}"
                ),
            )


async def trader_handle_candle_async(
    trader: DomainTrader,
    candle: DomainExchangeCandle,
):
    await trader.handle_candle(candle=candle)


@shared_task()
def trader_process(trader_id: int) -> None:
    """Обработка одной свечи для конкретного трейдера."""

    trader = Trader.objects.select_related(
        "exchange_client",
        "exchange_client__exchange",
        "exchange_client__proxy",
        "candle_source",
        "candle_source__trading_pair",
        "candle_source__exchange_client",
        "candle_source__exchange_client__exchange",
        "risk_manager",
        "strategy",
    ).get(id=trader_id)

    try:
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        last_candle = trader.get_last_candle()
        if last_candle:
            asyncio.run(
                trader_handle_candle_async(
                    trader=domain_trader,
                    candle=last_candle.instantiate(),
                )
            )
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


@shared_task(queue="traders_reboot")
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
        "candle_source__exchange_client",
        "candle_source__exchange_client__exchange",
        "risk_manager",
        "strategy",
    ).get(id=trader_id)
    trader.reboot()


@shared_task()
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

    pnl = round(result["pnl"], 2)
    fee = round(result["fee"], 2)

    send_notification.delay(
        message=(
            f"Ежедневный отчет по трейдерам за период "
            f"с {dt_str(start_date)} по {dt_str(end_date)}:\n"
            f"Общий PnL: {pnl}\n"
            f"Общие комиссии: {fee}\n"
        )
    )
