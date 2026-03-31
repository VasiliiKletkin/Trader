import asyncio
from functools import partial

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceError, CandleSourceMode
from exchange_clients.domain.pool import ClientEntry, ExchangeClientPool
from exchange_clients.domain.ws.manager import StreamWorker
from exchange_clients.domain.ws.streams import BaseStream, OHLCVStream
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from telegram_bots.tasks import send_notification

SYNC_INTERVAL = 60


class Command(BaseCommand):
    help = "Запускает все WebSocket стримы (свечи)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        redis_settings = settings.REDIS
        self.candle_cache = CandleRedisCache(
            host=redis_settings["HOST"],
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=redis_settings.get("PASSWORD") or None,
        )

    def handle(self, *args, **options):
        self.stdout.write("Запуск WebSocket стримов...")
        pool = ExchangeClientPool(
            loader=self._load_clients,
            sync_interval=SYNC_INTERVAL,
        )
        manager = StreamWorker(
            pool=pool,
            load_streams=self._load_streams,
            sync_interval=SYNC_INTERVAL,
        )
        asyncio.run(manager.run())

    @sync_to_async
    def _load_clients(self) -> dict[int, ClientEntry]:
        """Загружает exchange-клиентов для WS-источников."""
        clients: dict[int, ClientEntry] = {}
        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "exchange_client__proxy",
        )
        for source in sources:
            ec = source.exchange_client
            if ec.pk not in clients:
                try:
                    updated_at = max(ec.updated_at, ec.exchange.updated_at)
                    if ec.proxy:
                        updated_at = max(updated_at, ec.proxy.updated_at)
                    clients[ec.pk] = (ec.instantiate(), updated_at)
                except Exception as e:
                    logger.error(
                        f"Не удалось создать клиент {ec.name} (pk={ec.pk}): {e}"
                    )
        return clients

    @sync_to_async
    def _load_streams(self) -> dict[int, list[BaseStream]]:
        """Загружает конфигурацию стримов из БД."""
        streams: dict[int, list[BaseStream]] = {}
        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "trading_pair",
        )
        for source in sources:
            cid = source.exchange_client_id
            if cid not in streams:
                streams[cid] = []

            domain_tp = source.trading_pair.instantiate(
                exchange=source.exchange_client.exchange,
            )
            streams[cid].append(
                OHLCVStream(
                    trading_pair=domain_tp,
                    timeframe=Timeframe(source.timeframe),
                    on_candle=self._on_candle,
                    on_error=partial(
                        self._on_candle_error,
                        source_id=source.pk,
                    ),
                )
            )
        return streams

    async def _on_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        candle: Candle,
    ) -> None:
        await self.candle_cache.set_candle(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=timeframe,
            candle=candle,
        )

    @sync_to_async
    def _on_candle_error(self, error: Exception, tb: str, source_id: int) -> None:
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
