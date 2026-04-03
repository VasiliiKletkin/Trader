import asyncio
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from celery import group, shared_task
from django.db import models
from django.utils import timezone

from arbitrage_traders.domain import ArbitrageCandle as DomainArbitrageCandle
from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderOrder,
)
from arbitrage_traders.schemas import ArbitragePositionStatus, ArbitrageTraderStatus
from core.utils.common import dt_str
from exchange_clients.models import ExchangeClient
from telegram_bots.tasks import send_notification


@shared_task()
def dispatch_arbitrage_traders_for_sources(source_ids: list[int]):
    """Находит арбитражных трейдеров по источникам и запускает обработку."""
    traders: models.QuerySet[ArbitrageTrader] = ArbitrageTrader.objects.filter(
        models.Q(left_candle_source_id__in=source_ids)
        | models.Q(right_candle_source_id__in=source_ids),
        status__in=[
            ArbitrageTraderStatus.ENABLED,
            ArbitrageTraderStatus.PAUSED,
            ArbitrageTraderStatus.ERROR,
        ],
    ).select_related(
        "left_candle_source",
        "right_candle_source",
        "left_exchange_client",
        "right_exchange_client",
    )

    # Проверяем что оба источника синхронизированы в пределах 2 минут
    now = timezone.now()
    threshold = now - timedelta(minutes=2)

    ready_traders = [
        t
        for t in traders
        if t.left_candle_source.last_synced
        and t.right_candle_source.last_synced
        and t.left_candle_source.last_synced >= threshold
        and t.right_candle_source.last_synced >= threshold
    ]

    if not ready_traders:
        return

    # Группируем по паре (left_exchange_client, right_exchange_client)
    traders_by_clients: dict[tuple[int, int], list[int]] = defaultdict(list)
    for trader in ready_traders:
        key = (
            trader.left_exchange_client_id,
            trader.right_exchange_client_id,
        )
        traders_by_clients[key].append(trader.pk)

    group(
        arbitrage_traders_process_for_exchange_clients.s(
            left_exchange_client_id=left_id,
            right_exchange_client_id=right_id,
            traders_ids=traders_ids,
        )
        for (left_id, right_id), traders_ids in traders_by_clients.items()
    ).apply_async()


@shared_task()
def arbitrage_traders_process_for_exchange_clients(
    left_exchange_client_id: int,
    right_exchange_client_id: int,
    traders_ids: list[int],
) -> None:
    """Обработка свечи для арбитражных трейдеров с двумя exchange_client."""

    ExchangeClient.active_objects.get(id=left_exchange_client_id)
    ExchangeClient.active_objects.get(id=right_exchange_client_id)

    traders = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__exchange_client",
        "left_candle_source__exchange_client__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__exchange_client",
        "right_candle_source__exchange_client__exchange",
        "left_exchange_client",
        "left_exchange_client__exchange",
        "left_exchange_client__proxy",
        "right_exchange_client",
        "right_exchange_client__exchange",
        "right_exchange_client__proxy",
        "strategy",
        "risk_manager",
    ).filter(
        id__in=traders_ids,
        status__in=[
            ArbitrageTraderStatus.ENABLED,
            ArbitrageTraderStatus.PAUSED,
            ArbitrageTraderStatus.ERROR,
        ],
    )

    try:
        domain_traders: dict[ArbitrageTrader, DomainArbitrageTrader] = {}

        tasks = []
        for trader in traders:
            domain_trader = trader.instantiate()
            domain_traders[trader] = domain_trader
            trader.load(trader=domain_trader)
            last_candle = trader.get_last_candle()
            if last_candle:
                tasks.append(
                    arbitrage_trader_handle_candle_async(
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
            ArbitrageTraderError.objects.create(
                trader=trader,
                message=str(e),
                type=type(e).__name__,
            )
        trader_names = ", ".join(str(t) for t in traders)
        send_notification.delay(
            message=(
                f"Ошибка обработки арбитражных трейдеров: {trader_names}\n"
                f"[{type(e).__name__}]: {e}"
            ),
        )


async def arbitrage_trader_handle_candle_async(
    trader: DomainArbitrageTrader,
    candle: DomainArbitrageCandle,
):
    await trader.handle_candle(candle=candle)


@shared_task()
def arbitrage_trader_process(trader_id: int) -> None:
    """Обработка одной свечи для конкретного арбитражного трейдера."""

    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__exchange_client",
        "left_candle_source__exchange_client__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__exchange_client",
        "right_candle_source__exchange_client__exchange",
        "left_exchange_client",
        "left_exchange_client__exchange",
        "left_exchange_client__proxy",
        "right_exchange_client",
        "right_exchange_client__exchange",
        "right_exchange_client__proxy",
        "strategy",
        "risk_manager",
    ).get(id=trader_id)

    try:
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        last_candle = trader.get_last_candle()
        if last_candle:
            asyncio.run(
                arbitrage_trader_handle_candle_async(
                    trader=domain_trader,
                    candle=last_candle.instantiate(),
                )
            )
        trader.sync(trader=domain_trader)
    except Exception as e:
        ArbitrageTraderError.objects.create(
            trader=trader,
            message=str(e),
            type=type(e).__name__,
        )
        send_notification.delay(
            message=(
                f"Ошибка обработки арбитражного трейдера: {trader}\n"
                f"[{type(e).__name__}]: {e}"
            ),
        )
        raise


@shared_task(queue="traders_reboot")
def arbitrage_trader_reboot(trader_id: int):
    """
    Перезагружает арбитражного трейдера с историческими данными.
    """
    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__exchange_client",
        "left_candle_source__exchange_client__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__exchange_client",
        "right_candle_source__exchange_client__exchange",
        "left_exchange_client",
        "left_exchange_client__exchange",
        "left_exchange_client__proxy",
        "right_exchange_client",
        "right_exchange_client__exchange",
        "right_exchange_client__proxy",
        "strategy",
        "risk_manager",
    ).get(id=trader_id)
    trader.reboot()


@shared_task()
def arbitrage_traders_daily_report():
    end_date = timezone.now()
    start_date = end_date - timezone.timedelta(days=1)

    result = ArbitrageTraderOrder.objects.filter(
        position__status=ArbitragePositionStatus.CLOSED,
        position__closed_at__gte=start_date,
        position__closed_at__lt=end_date,
    ).aggregate(
        pnl=models.Sum(ArbitrageTrader.fact_pnl_annotation(), default=Decimal("0.00")),
        fee=models.Sum(
            models.F("left_order__fee") + models.F("right_order__fee"),
            default=Decimal("0.00"),
        ),
    )

    pnl = round(result["pnl"], 2)
    fee = round(result["fee"], 2)

    send_notification.delay(
        message=(
            f"Ежедневный отчет по арбитражным трейдерам за период "
            f"с {dt_str(start_date)} по {dt_str(end_date)}:\n"
            f"Общий PnL: {pnl}\n"
            f"Общие комиссии: {fee}\n"
        )
    )
