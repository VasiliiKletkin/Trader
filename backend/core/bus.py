"""Фабрики для BusClient."""

import redis.asyncio as aio_redis
from django.conf import settings

from core.utils.rpc import AbstractBusClient, BusClient, LocalBusClient
from core.utils.rpc.redis.broker import RedisBusBroker


def create_redis_bus_broker() -> RedisBusBroker:
    rs = settings.REDIS
    return RedisBusBroker(
        redis=aio_redis.Redis(
            host=str(rs["HOST"]),
            port=int(rs["PORT"]),
            db=int(rs["BUS_DATABASE"]),
            password=str(rs["PASSWORD"]) or None,
            decode_responses=True,
        ),
    )


def get_bus_client(local: bool = False) -> AbstractBusClient:
    """Создаёт BusClient.

    Каждый вызов создаёт новый экземпляр — синглтон нельзя
    использовать с asyncio.run(), т.к. redis-соединение
    привязывается к event loop, который закрывается после run().

    USE_BUS=True → BusClient (через Redis Streams, требует exchange_client_worker).
    USE_BUS=False → LocalBusClient (напрямую, без Redis).
    """
    if local:
        return LocalBusClient()
    return BusClient(broker=create_redis_bus_broker())
