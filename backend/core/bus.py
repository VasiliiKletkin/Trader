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


_client: AbstractBusClient | None = None


def get_bus_client(local: bool = False) -> AbstractBusClient:
    """Возвращает синглтон BusClient.

    USE_BUS=True → BusClient (через Redis Streams, требует exchange_client_worker).
    USE_BUS=False → LocalBusClient (напрямую, без Redis).
    """
    global _client
    if _client is None:
        _client = (
            LocalBusClient() if local else BusClient(broker=create_redis_bus_broker())
        )
    return _client
