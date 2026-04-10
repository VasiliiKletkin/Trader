from celery import group, shared_task
from django.db import models

from arbitrage_traders.models import ArbitrageTraderOrder
from exchange_clients.models import (
    ExchangeClientOrder,
)
from exchange_clients.schemas import OrderStatus
from traders.models import TraderOrder


@shared_task(queue="exchange_client")
def exchange_client_sync_order(order_id: int) -> None:
    """Синхронизирует один ордер с биржей и обновляет связанные позиции."""
    order = ExchangeClientOrder.objects.select_related(
        "exchange_client__exchange",
        "trading_pair",
    ).get(pk=order_id)
    order.sync_from_exchange()

    trader_order = (
        TraderOrder.objects.filter(order=order).select_related("position").first()
    )
    if trader_order:
        trader_order.position.refresh()

    arb_order = (
        ArbitrageTraderOrder.objects.filter(
            models.Q(left_order=order) | models.Q(right_order=order),
        )
        .select_related("position")
        .first()
    )
    if arb_order:
        arb_order.position.refresh()


@shared_task(queue="exchange_client")
def exchange_client_sync_open_orders() -> None:
    """Синхронизирует все открытые ордера, запускает exchange_client_sync_order для каждого."""
    order_ids = list(
        ExchangeClientOrder.objects.filter(
            status=OrderStatus.OPENED,
            exchange_client__is_active=True,
        ).values_list("id", flat=True)
    )

    if not order_ids:
        return

    tasks = group(exchange_client_sync_order.s(order_id=oid) for oid in order_ids)
    tasks.apply_async()
