import asyncio
from datetime import timedelta
from decimal import Decimal

import sentry_sdk
from celery import group, shared_task
from django.db import models
from django.utils import timezone

from arbitrage_traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderOrder,
    ArbitrageTraderSignal,
)
from arbitrage_traders.schemas import (
    ArbitragePositionStatus,
    ArbitrageSignalType,
    ArbitrageTraderStatus,
)
from core.utils.common import dt_str, format_fee, format_pnl
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
    )

    # Проверяем что оба источника синхронизированы в пределах 15 секунд
    now = timezone.now()
    threshold = now - timedelta(seconds=15)

    ready_ids = [
        t.pk
        for t in traders
        if t.left_candle_source.last_synced
        and t.right_candle_source.last_synced
        and t.left_candle_source.last_synced >= threshold
        and t.right_candle_source.last_synced >= threshold
    ]

    if not ready_ids:
        return

    tasks = group(arbitrage_trader_process.s(trader_id=tid) for tid in ready_ids)
    tasks.apply_async()


@shared_task()
def arbitrage_trader_process(trader_id: int) -> None:
    """Обработка одной свечи для конкретного арбитражного трейдера."""
    sentry_sdk.set_tag("trader_id", trader_id)
    sentry_sdk.set_tag("trader_kind", "arbitrage")

    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__trading_pair__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__trading_pair__exchange",
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
            asyncio.run(domain_trader.handle_candle(candle=last_candle.instantiate()))
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


@shared_task(queue="trader")
def arbitrage_trader_reboot(trader_id: int):
    """
    Перезагружает арбитражного трейдера с историческими данными.
    """
    sentry_sdk.set_tag("trader_id", trader_id)
    sentry_sdk.set_tag("trader_kind", "arbitrage")
    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__trading_pair__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__trading_pair__exchange",
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


@shared_task(queue="trader")
def arbitrage_trader_clear_all_data(trader_id: int):
    """Очистить все данные арбитражного трейдера."""
    trader = ArbitrageTrader.objects.get(id=trader_id)
    trader.clear_all_data()


@shared_task(queue="trader")
def arbitrage_trader_clear_all_errors(trader_id: int):
    """Удалить все ошибки арбитражного трейдера."""
    trader = ArbitrageTrader.objects.get(id=trader_id)
    trader.clear_all_errors()


@shared_task(queue="trader")
def arbitrage_traders_daily_report():
    end_date = timezone.now()
    start_date = end_date - timezone.timedelta(days=1)

    result = ArbitrageTraderOrder.objects.filter(
        position__status=ArbitragePositionStatus.CLOSED,
        position__closed_at__gte=start_date,
        position__closed_at__lt=end_date,
    ).aggregate(
        pnl=models.Sum(ArbitrageTrader.order_pnl_annotation(), default=Decimal("0.00")),
        fee=models.Sum(
            models.F("left_order__fee") + models.F("right_order__fee"),
            default=Decimal("0.00"),
        ),
    )

    pnl = format_pnl(result["pnl"])
    fee = format_fee(result["fee"])

    send_notification.delay(
        message=(
            f"Ежедневный отчет по арбитражным трейдерам за период "
            f"с {dt_str(start_date)} по {dt_str(end_date)}:\n"
            f"Общий PnL: {pnl}\n"
            f"Общие комиссии: {fee}\n"
        )
    )


@shared_task(queue="trader")
def arbitrage_traders_cleanup_signals():
    """Удаляет WAIT-сигналы старше часа, не связанные с открытием/закрытием позиции."""
    cutoff = timezone.now() - timezone.timedelta(hours=1)
    ArbitrageTraderSignal.objects.filter(
        left_type=ArbitrageSignalType.WAIT,
        right_type=ArbitrageSignalType.WAIT,
        timestamp__lt=cutoff,
        opened_position__isnull=True,
        closed_position__isnull=True,
    ).delete()
