"""Management command: запуск unified exchange client worker.

Объединяет в одном процессе:
- REST (RPCServer через Redis Streams)
- WS OHLCV (стриминг свечей через watch_ohlcv_for_symbols)
- WS Balance/Orders (стриминг балансов и ордеров)

Все используют один ExchangeClientPool → один ccxt-инстанс на аккаунт.
"""

import asyncio

from django.core.management.base import BaseCommand

from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.domain.workers import UnifiedExchangeClientWorker
from exchange_clients.domain.ws.loaders import (
    load_balance_streams,
    load_candle_subscriptions,
    load_clients,
    load_order_streams,
)


class Command(BaseCommand):
    help = (
        "Запускает unified exchange client worker (REST + WS OHLCV + WS балансы/ордера)"
    )

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = UnifiedExchangeClientWorker(
            pool=pool,
            load_candle_subscriptions=load_candle_subscriptions,
            load_balance_streams=load_balance_streams,
            load_order_streams=load_order_streams,
        )
        asyncio.run(worker.launch())
