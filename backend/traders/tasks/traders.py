import asyncio
from collections import defaultdict
from decimal import Decimal

from celery import group, shared_task
from django.db import models
from django.utils import timezone

from core.utils.common import dt_str
from exchange_clients.models import ExchangeClient
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.models import Trader, TraderError, TraderOrder
from traders.schemas import PositionStatus, TraderStatus


@shared_task()
def dispatch_traders_for_sources(source_ids: list[int]):
    """Находит трейдеров по источникам свечей и запускает обработку."""
    traders = (
        Trader.objects.filter(
            candle_source_id__in=source_ids,
            status__in=[
                TraderStatus.ENABLED,
                TraderStatus.PAUSED,
                TraderStatus.ERROR,
            ],
        )
        .select_related(
            "exchange_client",
        )
        .iterator()
    )

    traders_by_clients: dict[int, list[int]] = defaultdict(list)
    for trader in traders:
        traders_by_clients[trader.exchange_client.pk].append(trader.pk)

    if not traders_by_clients:
        return

    group(
        traders_process_for_exchange_client.s(
            exchange_client_id=exchange_client_id,
            traders_ids=traders_ids,
        )
        for exchange_client_id, traders_ids in traders_by_clients.items()
    ).apply_async()


@shared_task()
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
        domain_traders: dict[Trader, DomainTrader] = {}
        tasks = []
        for trader in traders:
            domain_trader = trader.instantiate()
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
        if tasks:

            async def _run():
                await asyncio.gather(*tasks)

            asyncio.run(_run())

        for trader, domain_trader in domain_traders.items():
            trader.sync(trader=domain_trader)
    except Exception as e:
        for trader in traders:
            TraderError.objects.create(
                trader=trader,
                message=str(e),
                type=type(e).__name__,
            )
        trader_names = ", ".join(str(t) for t in traders)
        send_notification.delay(
            message=(
                f"Ошибка обработки трейдеров: {trader_names}\n[{type(e).__name__}]: {e}"
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
