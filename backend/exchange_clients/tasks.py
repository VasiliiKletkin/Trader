from celery import shared_task
from django.db import models

from arbitrage_traders.models import ArbitrageTraderOrder
from exchange_clients.models import (
    ExchangeClientOrder,
)
from exchange_clients.schemas import OrderStatus
from traders.models import TraderOrder


@shared_task()
def sync_exchange_order(order_id: int) -> None:
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


@shared_task()
def sync_open_orders() -> None:
    """Синхронизирует все открытые ордера с биржами и обновляет связанные позиции."""
    orders = list(
        ExchangeClientOrder.objects.filter(
            status=OrderStatus.OPENED,
            exchange_client__is_active=True,
        ).select_related(
            "exchange_client__exchange",
            "trading_pair",
        )
    )
    for order in orders:
        order.sync_from_exchange()

    if not orders:
        return

    for to in TraderOrder.objects.filter(
        order_id__in=orders,
    ).select_related("position"):
        to.position.refresh()

    for ato in ArbitrageTraderOrder.objects.filter(
        models.Q(left_order__in=orders) | models.Q(right_order__in=orders),
    ).select_related("position"):
        ato.position.refresh()
