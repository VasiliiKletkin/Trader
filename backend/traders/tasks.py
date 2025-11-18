import asyncio
from decimal import Decimal
from typing import Dict, List, Optional

from celery import shared_task
from core.utils.types import OrderSide, PositionStatus, TraderStatus
from django.db import models
from django.utils import timezone
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from loguru import logger
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.models import Trader, TraderOrder, TraderPosition


@shared_task(queue="traders_process_for_exchange_client")
def traders_process_for_exchange_client(
    exchange_client_id: int,
    traders_ids: List[int],
) -> None:
    """Обработка свечи для трейдеров конкретного exchange_client."""
    logger.info(
        f"Начало обработки свечей для exchange_client {exchange_client_id} с трейдерами {traders_ids}"
    )

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)
    traders = Trader.objects.filter(
        id__in=traders_ids,
        exchange_client=exchange_client,
        status=TraderStatus.ENABLED,
    ).select_related("exchange_client", "exchange_client__exchange", "trading_pair")
    logger.info(f"Найдено {len(traders)} трейдеров для обработки")

    domain_exchange_client = exchange_client.instantiate()
    domain_traders: Dict[Trader, DomainTrader] = {}

    tasks = []
    for trader in traders:
        domain_trader = trader.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        trader.load(trader=domain_trader)
        domain_traders[trader] = domain_trader

        current_candle, previous_candle = (
            list(trader.candles.order_by("-timestamp")[:2]) + [None, None]
        )[:2]

        if previous_candle and trader.has_existing_signal(previous_candle):
            tasks.append(
                trader_check_opened_positions_async(
                    trader=domain_trader,
                    candle=current_candle.instantiate() if current_candle else None,
                )
            )
        else:
            tasks.append(
                trader_handle_candle_async(
                    trader=domain_trader,
                    candle=previous_candle.instantiate() if previous_candle else None,
                )
            )

    asyncio.run(
        run_tasks_with_exchange_client(
            exchange_client=domain_exchange_client,
            tasks=tasks,
        )
    )

    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)
    logger.info(f"Завершена обработка свечей для exchange_client {exchange_client_id}")


async def trader_check_opened_positions_async(
    trader: DomainTrader,
    candle: Optional[DomainCandle],
):
    logger.info(f"Начало проверки открытых позиций для трейдера {trader}")
    if candle is None:
        logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
        return
    await trader.check_opened_positions(
        candle=candle,
    )
    logger.info(f"Завершена проверка открытых позиций для трейдера {trader}")


async def trader_handle_candle_async(
    trader: DomainTrader,
    candle: Optional[DomainCandle],
):
    logger.info(f"Начало обработки свечи для трейдера {trader}")
    if candle is None:
        logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
        return
    await trader.handle_candle(
        candle=candle,
    )
    logger.info(f"Завершена обработка свечи для трейдера {trader}")


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: List[asyncio.Task],
):
    async with exchange_client:
        await asyncio.gather(*tasks)


@shared_task(queue="trader_reboot")
def trader_reboot(trader_id: int):
    logger.info(f"Начало перезагрузки трейдера {trader_id}")
    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        logger.error(f"Trader с id {trader_id} не существует.")
        return
    trader.reboot()
    logger.info(f"Завершена перезагрузка трейдера {trader_id}")


@shared_task()
def traders_daily_report():
    end_date = timezone.now()
    start_date = end_date - timezone.timedelta(days=1)

    positions = TraderPosition.objects.filter(status=PositionStatus.CLOSED)
    if start_date:
        positions = positions.filter(closed_at__gte=start_date)
    if end_date:
        positions = positions.filter(closed_at__lt=end_date)

    orders = TraderOrder.objects.filter(position__in=positions)
    result = orders.aggregate(
        pnl=models.Sum(
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
        fee=models.Sum("order__fee"),
        fact_profit=models.functions.Coalesce(
            models.F("pnl") - models.F("fee"), Decimal("0.00")
        ),
    )
    send_notification.delay(
        message=(
            f"Ежедневный отчет по трейдерам за период с {start_date} по {end_date}:\n"
            f"Общий PnL: {result['pnl'] or Decimal('0.00')}\n"
            f"Общие комиссии: {result['fee'] or Decimal('0.00')}\n"
            f"Чистая прибыль: {result['fact_profit'] or Decimal('0.00')}\n"
        )
    )
