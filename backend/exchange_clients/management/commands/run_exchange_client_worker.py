"""Management command: запуск exchange worker."""

import asyncio

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from loguru import logger

from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.messages.worker import ExchangeClientWorker
from exchange_clients.domain.pool import ExchangeClientPool
from exchange_clients.models import ExchangeClient


@sync_to_async
def load_clients() -> dict[int, AbstractExchangeClient]:
    clients: dict[int, AbstractExchangeClient] = {}
    for ec in ExchangeClient.active_objects.select_related("exchange", "proxy"):
        try:
            clients[ec.pk] = ec.instantiate()
        except Exception as e:
            logger.error(f"Не удалось создать клиент {ec.name} (pk={ec.pk}): {e}")
    return clients


class Command(BaseCommand):
    help = "Запускает exchange worker"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = ExchangeClientWorker(pool=pool)
        asyncio.run(worker.launch())
