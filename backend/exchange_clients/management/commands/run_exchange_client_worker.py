"""Management command: запуск exchange worker."""

import asyncio

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand

from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.commands.bus import create_worker
from exchange_clients.domain.commands.pool import ExchangeClientPool
from exchange_clients.models import ExchangeClient


@sync_to_async
def load_clients() -> dict[int, AbstractExchangeClient]:
    return {
        ec.pk: ec.instantiate()
        for ec in ExchangeClient.active_objects.select_related("exchange", "proxy")
    }


class Command(BaseCommand):
    help = "Запускает exchange worker"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        worker = create_worker(pool=pool)
        asyncio.run(worker.launch())
