"""Management command: запуск candle stream worker (только WS свечи)."""

import asyncio

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceMode
from exchange_clients.domain.managers import (
    ClientEntry,
    ExchangeClientPool,
    StreamManager,
)
from exchange_clients.domain.streams import BaseStream, CandleStream
from exchange_clients.domain.workers import CandleStreamWorker
from exchange_clients.models import ExchangeClient
from exchanges.domain import Timeframe

_candle_cache = None


def _get_candle_cache():
    global _candle_cache
    if _candle_cache is None:
        rs = settings.REDIS
        _candle_cache = CandleRedisCache(
            host=str(rs["HOST"]),
            port=int(rs["PORT"]),
            db=int(rs["EXCHANGE_CACHE_DATABASE"]),
            password=str(rs["PASSWORD"]) if rs.get("PASSWORD") else None,
        )
    return _candle_cache


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


@sync_to_async
def load_candle_streams() -> dict[tuple, BaseStream]:
    """Загружает WS-стримы свечей для активных источников."""
    cache = _get_candle_cache()
    streams: dict[tuple, BaseStream] = {}
    sources = CandleSource.active_objects.filter(
        mode=CandleSourceMode.WEBSOCKET,
    ).select_related(
        "exchange_client",
        "exchange_client__exchange",
        "trading_pair",
    )
    for source in sources:
        cid = source.exchange_client_id
        domain_tp = source.trading_pair.instantiate(
            exchange=source.exchange_client.exchange,
        )
        stream = CandleStream(
            exchange_client_id=cid,
            cache=cache,
            trading_pair=domain_tp,
            timeframe=Timeframe(source.timeframe),
        )
        streams[stream.key] = stream
    return streams


class Command(BaseCommand):
    help = "Запускает candle stream worker (WS свечи через watch_ohlcv)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        stream_manager = StreamManager(pool=pool, load_streams=load_candle_streams)
        worker = CandleStreamWorker(pool=pool, stream_manager=stream_manager)
        asyncio.run(worker.launch())
