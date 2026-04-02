"""Management command: запуск balance stream worker (WS балансы и ордера)."""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.workers import BalanceStreamWorker
from exchange_clients.domain.ws.loaders import load_balance_streams, load_clients


class Command(BaseCommand):
    help = "Запускает balance stream worker (WS балансы и ордера)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = BalanceStreamWorker(pool=pool, load_streams=load_balance_streams)
        asyncio.run(worker.launch())
