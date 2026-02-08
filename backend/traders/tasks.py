import asyncio
from decimal import Decimal

from celery import shared_task
from django.db import models
from django.utils import timezone
from loguru import logger

from core.utils.common import dt_str
from core.utils.types import OrderSide, PositionStatus, TraderStatus
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.models import Trader, TraderOrder


@shared_task(queue="traders_process_for_exchange_client")
def traders_process_for_exchange_client(
    exchange_client_id: int,
    traders_ids: list[int],
) -> None:
    """Обработка свечи для трейдеров конкретного exchange_client."""

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange",
        "proxy",
    ).get(id=exchange_client_id)

    traders: list[Trader] = Trader.objects.select_related(
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

    domain_exchange_client = exchange_client.instantiate()
    domain_traders: dict[Trader, DomainTrader] = {}

    # Собираем свечи для каждого трейдера
    candles_by_trader: dict[int, list] = {}
    for trader in traders:
        candles_by_trader[trader.pk] = trader.get_last_candles(count=2)

    tasks = []
    for trader in traders:
        domain_trader = trader.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        trader.load(trader=domain_trader)
        domain_traders[trader] = domain_trader

        source_candles = candles_by_trader.get(trader.pk, [])
        candles_with_padding = [*source_candles, None, None]
        current_candle, previous_candle = (
            candles_with_padding[0],
            candles_with_padding[1],
        )

        if previous_candle and trader.has_existing_signal(previous_candle):
            tasks.append(
                trader_check_opened_positions_async(
                    trader=domain_trader,
                    candle=current_candle,
                )
            )
        else:
            tasks.append(
                trader_handle_candle_async(
                    trader=domain_trader,
                    candle=previous_candle,
                )
            )

    if tasks:
        asyncio.run(
            run_tasks_with_exchange_client(
                exchange_client=domain_exchange_client,
                tasks=tasks,
            )
        )

    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)


async def trader_check_opened_positions_async(
    trader: DomainTrader,
    candle: DomainExchangeCandle | None,
):
    if candle is None:
        logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
        return
    await trader.check_opened_positions(
        candle=candle,
    )


async def trader_handle_candle_async(
    trader: DomainTrader,
    candle: DomainExchangeCandle | None,
):
    if candle is None:
        logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
        return
    await trader.handle_candle(
        candle=candle,
    )


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: list[asyncio.Task],
):
    async with exchange_client:
        await asyncio.gather(*tasks)


@shared_task(queue="trader_reboot")
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
        pnl=models.functions.Coalesce(
            models.Sum(
                models.Case(
                    models.When(
                        order__side=OrderSide.SELL,
                        then=models.F("order__price") * models.F("order__amount"),
                    ),
                    models.When(
                        order__side=OrderSide.BUY,
                        then=-models.F("order__price") * models.F("order__amount"),
                    ),
                    default=Decimal("0.00"),
                    output_field=models.DecimalField(max_digits=30, decimal_places=18),
                )
            ),
            Decimal("0.00"),
        ),
        fee=models.functions.Coalesce(
            models.Sum("order__fee"),
            Decimal("0.00"),
        ),
    )

    pnl = round(result["pnl"], 2)
    fee = round(result["fee"], 2)
    fact_profit = round(pnl - fee, 2)

    send_notification.delay(
        message=(
            f"Ежедневный отчет по трейдерам за период "
            f"с {dt_str(start_date)} по {dt_str(end_date)}:\n"
            f"Общий PnL: {pnl}\n"
            f"Общие комиссии: {fee}\n"
            f"Чистая прибыль: {fact_profit}\n"
        )
    )
