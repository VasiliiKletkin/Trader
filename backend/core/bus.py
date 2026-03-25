"""Фабрики для BusClient и BusWorker."""

import redis.asyncio as aio_redis
from django.conf import settings

from core.utils.cqrs import BusClient, BusWorker
from core.utils.cqrs.redis.broker import RedisBusBroker


def create_redis_broker() -> RedisBusBroker:
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


_client: BusClient | None = None


def get_bus_client() -> BusClient:
    """Возвращает синглтон BusClient."""
    global _client
    if _client is None:
        _client = BusClient(broker=create_redis_broker())
    return _client


_worker: BusWorker | None = None


def get_bus_worker() -> BusWorker:
    """Возвращает синглтон BusWorker."""
    global _worker
    if _worker is None:
        _worker = BusWorker(broker=create_redis_broker())
    return _worker
