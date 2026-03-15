import asyncio
from functools import partial

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceError, CandleSourceMode
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain.ws.manager import ExchangeConnection, StreamManager
from exchange_clients.domain.ws.streams import OHLCVStream
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from telegram_bots.tasks import send_notification


class Command(BaseCommand):
    help = "Запускает WebSocket стримы для получения OHLCV свечей"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        redis_settings = settings.REDIS
        self.redis_cache = CandleRedisCache(
            host=redis_settings["HOST"],
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["CANDLE_CACHE_DATABASE"]),
            password=redis_settings.get("PASSWORD") or None,
        )

    def handle(self, *args, **options):
        self.stdout.write("Запуск WebSocket стримов свечей...")
        manager = StreamManager(
            load_connections=self._load_connections,
            sync_interval=60,
        )
        asyncio.run(manager.run())

    @sync_to_async
    def _load_connections(
        self,
    ) -> dict[int, ExchangeConnection]:
        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "exchange_client__proxy",
            "trading_pair",
        )

        clients: dict[int, DomainExchangeClient] = {}
        streams: dict[int, list] = {}

        for source in sources:
            cid = source.exchange_client_id
            if cid not in clients:
                clients[cid] = source.exchange_client.instantiate()
                streams[cid] = []

            domain_source = source.instantiate(domain_exchange_client=clients[cid])
            streams[cid].append(
                OHLCVStream(
                    trading_pair=domain_source.trading_pair,
                    timeframe=domain_source.timeframe,
                    on_candle=self._on_candle,
                    on_error=partial(self._on_error, source_id=source.pk),
                )
            )

        return {
            cid: ExchangeConnection(
                exchange_client=clients[cid],
                streams=streams[cid],
            )
            for cid in clients
        }

    async def _on_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        candle: Candle,
    ) -> None:
        await self.redis_cache.set_candle(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=timeframe,
            candle=candle,
        )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str, source_id: int) -> None:
        error_type = type(error).__name__
        logger.error(
            f"WS ошибка для источника {source_id} [{error_type}]: {error}\n{tb}"
        )
        CandleSourceError.objects.create(
            candle_source_id=source_id,
            message=str(error),
            type=error_type,
            traceback=tb,
        )
        send_notification.delay(
            message=(
                f"WebSocket ошибка для источника {source_id}\n[{error_type}]: {error}"
            ),
        )
