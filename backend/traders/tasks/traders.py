import asyncio
from decimal import Decimal

from celery import shared_task
from django.db import models
from django.utils import timezone

from core.utils.common import dt_str
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.models import Trader, TraderOrder
from traders.schemas import PositionStatus, TraderStatus


@shared_task(queue="traders_process")
def traders_process_for_exchange_client(
    exchange_client_id: int,
    traders_ids: list[int],
) -> None:
    """Обработка свечи для трейдеров конкретного exchange_client."""

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange",
        "proxy",
    ).get(id=exchange_client_id)

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
        exchange_client=exchange_client,
        status__in=[
            TraderStatus.ENABLED,
            TraderStatus.PAUSED,
            TraderStatus.ERROR,
        ],
    )

    try:
        domain_exchange_client = exchange_client.instantiate()
        domain_traders: dict[Trader, DomainTrader] = {}
        tasks = []
        for trader in traders:
            domain_trader = trader.instantiate(
                domain_exchange_client=domain_exchange_client
            )
            domain_traders[trader] = domain_trader
            trader.load(trader=domain_trader)
            last_candle = trader.get_last_candle()
            if last_candle:
                tasks.append(
                    trader_handle_candle_async(
                        trader=domain_trader,
                        candle=last_candle.instantiate(),
                    )
                )
        asyncio.run(
            run_tasks_with_exchange_client(
                exchange_client=domain_exchange_client,
                tasks=tasks,  # type: ignore[arg-type]
            )
        )

        for trader, domain_trader in domain_traders.items():
            trader.sync(trader=domain_trader)
    except Exception as e:
        trader_names = ", ".join(str(t) for t in traders)
        send_notification.delay(
            message=(
                f"Ошибка обработки трейдеров: {trader_names}\n[{type(e).__name__}]: {e}"
            ),
        )
        raise


async def trader_handle_candle_async(
    trader: DomainTrader,
    candle: DomainExchangeCandle,
):
    await trader.handle_candle(candle=candle)


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: list[asyncio.Task],  # type: ignore[arg-type]
):
    async with exchange_client:
        await asyncio.gather(*tasks)


@shared_task(queue="traders_process")
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
        domain_exchange_client = trader.exchange_client.instantiate()
        domain_trader = trader.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        trader.load(trader=domain_trader)
        last_candle = trader.get_last_candle()
        if last_candle:
            asyncio.run(
                run_tasks_with_exchange_client(
                    exchange_client=domain_exchange_client,
                    tasks=[
                        trader_handle_candle_async(  # type: ignore[list-item]
                            trader=domain_trader,
                            candle=last_candle.instantiate(),
                        )
                    ],
                )
            )
        trader.sync(trader=domain_trader)
    except Exception as e:
        send_notification.delay(
            message=(f"Ошибка обработки трейдера: {trader}\n[{type(e).__name__}]: {e}"),
        )
        raise


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
