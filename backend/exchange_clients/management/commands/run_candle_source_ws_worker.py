"""Management command: запуск candle stream worker (только WS свечи)."""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.workers import CandleStreamWorker
from exchange_clients.domain.ws.loaders import load_clients


class Command(BaseCommand):
    help = "Запускает candle stream worker (WS свечи через watch_ohlcv)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = CandleStreamWorker(pool=pool)
        asyncio.run(worker.launch())
