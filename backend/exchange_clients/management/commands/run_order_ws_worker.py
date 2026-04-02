"""Management command: запуск order stream worker (WS ордера)."""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.workers import OrderStreamWorker
from exchange_clients.domain.ws.loaders import load_clients, load_order_streams


class Command(BaseCommand):
    help = "Запускает order stream worker (WS ордера)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = OrderStreamWorker(pool=pool, load_streams=load_order_streams)
        asyncio.run(worker.launch())
