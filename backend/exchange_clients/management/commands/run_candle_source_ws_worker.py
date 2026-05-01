"""Management command: запуск candle stream worker (только WS свечи)."""

import asyncio

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource
from candle_sources.schemas import CandleSourceStatus
from exchange_clients.domain.managers import (
    ClientEntry,
    ExchangeClientPool,
    StreamManager,
)
from exchange_clients.domain.streams import BaseStream, CandleStream
from exchange_clients.domain.workers import CandleStreamWorker
from exchanges.domain import Timeframe
from exchanges.models import Exchange
from exchanges.schemas import CandleSourceMode

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
def load_public_clients() -> dict[int, ClientEntry]:
    """Загружает по одному публичному клиенту на каждую активную биржу."""
    clients: dict[int, ClientEntry] = {}
    for exchange in Exchange.active_objects.all():
        try:
            client = exchange.instantiate_public_client()
            clients[exchange.pk] = ClientEntry(client, exchange.updated_at)
        except Exception as e:
            logger.error(
                f"Не удалось создать публичный клиент для {exchange.name} "
                f"(pk={exchange.pk}): {e}"
            )
    return clients


@sync_to_async
def load_candle_streams() -> dict[tuple, BaseStream]:
    """Загружает WS-стримы свечей, дедуплицированные по (exchange, pair, timeframe)."""
    cache = _get_candle_cache()
    streams: dict[tuple, BaseStream] = {}
    sources = (
        CandleSource.objects.exclude(
            status=CandleSourceStatus.DISABLED,
        )
        .filter(
            trading_pair__exchange__candle_source_mode=CandleSourceMode.WEBSOCKET,
        )
        .select_related(
            "trading_pair__exchange",
        )
    )
    for source in sources:
        exchange = source.trading_pair.exchange
        domain_tp = source.trading_pair.instantiate()
        timeframe = Timeframe(source.timeframe)
        # Ключ по exchange_id — StreamManager найдёт публичный клиент в пуле
        stream = CandleStream(
            exchange_client_id=exchange.pk,
            cache=cache,
            trading_pair=domain_tp,
            timeframe=timeframe,
        )
        # Дедупликация: один стрим на (exchange, symbol, timeframe)
        streams[stream.key] = stream
    return streams


class Command(BaseCommand):
    help = "Запускает candle stream worker (WS свечи через watch_ohlcv)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_public_clients)
        stream_manager = StreamManager(pool=pool, load_streams=load_candle_streams)
        worker = CandleStreamWorker(pool=pool, stream_manager=stream_manager)
        asyncio.run(worker.launch())
