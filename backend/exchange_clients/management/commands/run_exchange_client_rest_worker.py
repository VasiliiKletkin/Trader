"""Management command: запуск exchange client bus worker (только REST)."""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.workers import ExchangeClientBusWorker
from exchange_clients.domain.ws.loaders import load_clients


class Command(BaseCommand):
    help = "Запускает exchange client bus worker (только REST через Redis Streams)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = ExchangeClientBusWorker(pool=pool)
        asyncio.run(worker.launch())
