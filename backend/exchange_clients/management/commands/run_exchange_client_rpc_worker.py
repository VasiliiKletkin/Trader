"""Management command: запуск exchange client RPC worker."""

import asyncio

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from loguru import logger

from core.bus import create_redis_bus_broker
from exchange_clients.domain.managers import ClientEntry, ExchangeClientPool
from exchange_clients.domain.rpc.server import ExchangeClientRPCServer
from exchange_clients.domain.workers import RPCWorker
from exchange_clients.models import ExchangeClient


@sync_to_async
def load_clients() -> dict[int, ClientEntry]:
    """Загружает активных exchange client'ов для ExchangeClientPool."""
    clients: dict[int, ClientEntry] = {}
    for ec in ExchangeClient.active_objects.select_related("exchange", "proxy"):
        try:
            timestamps = [ec.updated_at, ec.exchange.updated_at]
            if ec.proxy:
                timestamps.append(ec.proxy.updated_at)
            updated_at = max(timestamps)
            clients[ec.pk] = ClientEntry(ec.instantiate(), updated_at)
        except Exception as e:
            logger.error(f"Не удалось создать клиент {ec.name} (pk={ec.pk}): {e}")
    return clients


class Command(BaseCommand):
    help = "Запускает RPC worker"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        rpc_server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        worker = RPCWorker(pool=pool, rpc_server=rpc_server)
        asyncio.run(worker.launch())
