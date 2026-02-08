import asyncio

from celery import shared_task

from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain import ExchangeClientBalance as DomainExchangeClientBalance
from exchange_clients.models import ExchangeClient, ExchangeClientBalance


@shared_task()
def exchange_clients_fetch_balances() -> None:
    exchange_clients: list[ExchangeClient] = list(
        ExchangeClient.active_objects.select_related("exchange", "proxy").all()
    )

    async def fetch_all_balances(exchange_clients: list[ExchangeClient]):
        tasks = [get_balances(client.instantiate()) for client in exchange_clients]
        return await asyncio.gather(*tasks)

    async def get_balances(
        exchange_client: DomainExchangeClient,
    ) -> list[DomainExchangeClientBalance]:
        async with exchange_client:
            return await exchange_client.get_balances()

    domain_balances = asyncio.run(fetch_all_balances(exchange_clients=exchange_clients))

    balances = [
        ExchangeClientBalance(
            exchange_client=exchange_client,
            currency=balance.currency,
            total=balance.total,
            debt=balance.debt,
            free=balance.free,
            used=balance.used,
        )
        for exchange_client, client_domain_balances in zip(
            exchange_clients, domain_balances
        )
        for balance in client_domain_balances
    ]

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
