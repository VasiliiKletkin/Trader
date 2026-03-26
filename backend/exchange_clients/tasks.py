import asyncio

from celery import shared_task
from loguru import logger

from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain import ExchangeClientBalance as DomainExchangeClientBalance
from exchange_clients.models import (
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
)
from exchange_clients.schemas import OrderStatus


@shared_task()
def sync_exchange_order(order_id: int) -> None:
    order = ExchangeClientOrder.objects.select_related(
        "exchange_client__exchange",
        "trading_pair",
    ).get(pk=order_id)
    order.sync_from_exchange()


@shared_task()
def sync_open_orders() -> None:
    """Синхронизирует все открытые ордера с биржами."""
    orders = ExchangeClientOrder.objects.filter(
        status=OrderStatus.OPENED,
    ).select_related(
        "exchange_client__exchange",
        "trading_pair",
    )
    for order in orders:
        order.sync_from_exchange()


@shared_task()
def exchange_clients_fetch_balances() -> None:
    exchange_clients: list[ExchangeClient] = list(
        ExchangeClient.active_objects.select_related("exchange", "proxy").all()
    )

    async def fetch_all_balances(exchange_clients: list[ExchangeClient]):
        tasks = [get_balances(client.instantiate()) for client in exchange_clients]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def get_balances(
        exchange_client: DomainExchangeClient,
    ) -> list[DomainExchangeClientBalance]:
        async with exchange_client:
            return await exchange_client.get_balances()

    results = asyncio.run(fetch_all_balances(exchange_clients=exchange_clients))

    balances = []
    for exchange_client, result in zip(exchange_clients, results):
        if isinstance(result, Exception):
            logger.error(f"Ошибка получения балансов для {exchange_client}: {result}")
            continue
        for balance in result:
            balances.append(
                ExchangeClientBalance(
                    exchange_client=exchange_client,
                    currency=balance.currency,
                    total=balance.total,
                    debt=balance.debt,
                    free=balance.free,
                    used=balance.used,
                )
            )

    if balances:
        ExchangeClientBalance.objects.bulk_create(
            balances,
            update_conflicts=True,
            update_fields=[
                "free",
                "used",
                "debt",
                "total",
                "updated_at",
            ],
            unique_fields=[
                "exchange_client",
                "currency",
            ],
        )
