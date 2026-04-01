"""Management command: запуск balance stream worker (WS балансы и ордера)."""

import asyncio

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from loguru import logger

from exchange_clients.domain.pool import ClientEntry, ExchangeClientPool
from exchange_clients.domain.ws.balance_worker import BalanceStreamWorker
from exchange_clients.models import ExchangeClient


@sync_to_async
def load_clients() -> dict[int, ClientEntry]:
    clients: dict[int, ClientEntry] = {}
    for ec in ExchangeClient.active_objects.select_related("exchange", "proxy"):
        try:
            timestamps = [ec.updated_at, ec.exchange.updated_at]
            if ec.proxy:
                timestamps.append(ec.proxy.updated_at)
            updated_at = max(timestamps)
            clients[ec.pk] = (ec.instantiate(), updated_at)
        except Exception as e:
            logger.error(f"Не удалось создать клиент {ec.name} (pk={ec.pk}): {e}")
    return clients


class Command(BaseCommand):
    help = "Запускает balance stream worker (WS балансы и ордера)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = BalanceStreamWorker(pool=pool)
        asyncio.run(worker.launch())
