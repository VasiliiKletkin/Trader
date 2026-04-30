import asyncio
import json

import sentry_sdk
from celery import group, shared_task
from django.db import models
from loguru import logger

from arbitrage_traders.models import ArbitrageTraderError, ArbitrageTraderOrder
from exchange_clients.models import ExchangeClientOrder
from exchange_clients.schemas import OrderStatus
from traders.models import TraderError, TraderOrder

CANCELED_ERROR_TYPE = "OrderCanceledByExchange"


async def _fetch_raw_order_info(order: ExchangeClientOrder) -> dict:
    """Прямой ccxt-вызов в обход RPC — возвращает сырое поле info ответа
    биржи. Diagnostic-запрос только для отменённых ордеров: достать
    причину отмены, которая теряется при нормализации в
    DomainExchangeClientOrder.
    """
    domain_client = order.exchange_client.instantiate()
    domain_pair = order.trading_pair.instantiate(
        exchange=order.exchange_client.exchange,
    )
    async with domain_client:
        raw: dict = await domain_client.client.fetch_order(
            id=order.exchange_order_id,
            symbol=domain_pair.symbol,
        )
    return raw.get("info") or {}


def _safe_fetch_cancel_info(order: ExchangeClientOrder) -> dict:
    """Безопасная обёртка над _fetch_raw_order_info: при любых сбоях
    возвращает пустой dict и логирует warning."""
    try:
        return asyncio.run(_fetch_raw_order_info(order))
    except Exception as e:
        logger.warning(
            f"Не удалось получить raw info для отменённого ордера "
            f"{order.pk} ({order.exchange_order_id}): {e}"
        )
        return {}


def _build_cancel_message(order: ExchangeClientOrder, info: dict) -> str:
    info_str = json.dumps(info, default=str, ensure_ascii=False) if info else "{}"
    return (
        f"Ордер отменён биржей "
        f"(order_id={order.pk}, "
        f"exchange_order_id={order.exchange_order_id}, "
        f"symbol={order.trading_pair.name}, "
        f"side={order.side}, amount={order.amount}, cost={order.cost})"
        f"\nInfo: {info_str}"
    )


@shared_task(queue="exchange_client")
def exchange_client_sync_order(order_id: int) -> None:
    """Синхронизирует один OPENED-ордер с биржей и обновляет позиции.

    Если статус стал CANCELED — отдельным прямым (без RPC) ccxt-запросом
    достаёт raw info с причиной отмены и пишет в ошибку трейдера.
    """
    order = ExchangeClientOrder.objects.select_related(
        "exchange_client__exchange",
        "trading_pair",
    ).get(pk=order_id)
    sentry_sdk.set_tag("order_id", order_id)
    sentry_sdk.set_tag("exchange", order.exchange_client.exchange.name)
    sentry_sdk.set_tag("exchange_order_id", order.exchange_order_id)
    try:
        order.sync_from_exchange()
    except Exception as e:
        logger.warning(
            f"Не удалось синхронизировать ордер {order.pk} "
            f"({order.exchange_order_id}): {e}"
        )
        return

    is_canceled = order.status == OrderStatus.CANCELED
    cancel_info = _safe_fetch_cancel_info(order) if is_canceled else {}

    trader_order = (
        TraderOrder.objects.filter(order=order)
        .select_related("position__trader")
        .first()
    )
    if trader_order:
        trader_order.position.refresh()
        if is_canceled:
            TraderError.objects.create(
                trader=trader_order.position.trader,
                message=_build_cancel_message(order, cancel_info),
                type=CANCELED_ERROR_TYPE,
            )

    arb_order = (
        ArbitrageTraderOrder.objects.filter(
            models.Q(left_order=order) | models.Q(right_order=order),
        )
        .select_related("position__trader")
        .first()
    )
    if arb_order:
        arb_order.position.refresh()
        if is_canceled:
            ArbitrageTraderError.objects.create(
                trader=arb_order.position.trader,
                message=_build_cancel_message(order, cancel_info),
                type=CANCELED_ERROR_TYPE,
            )


@shared_task(queue="exchange_client")
def exchange_client_sync_open_orders() -> None:
    """Запускает sync для всех активных ордеров со статусом OPENED."""
    order_ids = list(
        ExchangeClientOrder.objects.filter(
            status=OrderStatus.OPENED,
            exchange_client__is_active=True,
        ).values_list("id", flat=True)
    )
    if not order_ids:
        return
    group(exchange_client_sync_order.s(order_id=oid) for oid in order_ids).apply_async()
