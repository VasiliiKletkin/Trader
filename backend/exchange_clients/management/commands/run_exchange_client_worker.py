"""Management command: запуск exchange client worker (REST + WS балансы/ордера)."""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.workers import ExchangeClientWorker
from exchange_clients.domain.ws.loaders import (
    load_balance_streams,
    load_clients,
    load_order_streams,
)


class Command(BaseCommand):
    help = "Запускает exchange client worker (REST + WS балансы/ордера)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = ExchangeClientWorker(
            pool=pool,
            load_balance_streams=load_balance_streams,
            load_order_streams=load_order_streams,
        )
        asyncio.run(worker.launch())
