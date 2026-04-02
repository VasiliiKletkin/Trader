"""Management command: запуск candle stream worker (только WS свечи)."""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.loaders import load_candle_streams, load_clients
from exchange_clients.domain.managers import ExchangeClientPool
from exchange_clients.domain.workers import CandleStreamWorker


class Command(BaseCommand):
    help = "Запускает candle stream worker (WS свечи через watch_ohlcv)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = CandleStreamWorker(
            pool=pool,
            load_streams=load_candle_streams,
        )
        asyncio.run(worker.launch())
