import asyncio
import traceback

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from candle_sources.domain.candle_sources import CandleSource as DomainCandleSource
from candle_sources.domain.ws.manager import WebSocketStreamManager
from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceError, CandleSourceMode
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
        self.stdout.write("Запуск WebSocket стримов...")
        manager = WebSocketStreamManager(
            load_subscriptions=self._load_subscriptions,
            on_candle=self._on_candle,
            on_error=self._on_error,
            sync_interval=30,
        )
        asyncio.run(manager.run())

    @sync_to_async
    def _load_subscriptions(self) -> list[DomainCandleSource]:
        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "exchange_client__proxy",
            "trading_pair",
        )

        return [source.instantiate() for source in sources]

    async def _on_candle(
        self,
        source_id: int,
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
    def _on_error(self, source_id: int, error: Exception) -> None:
        error_type = type(error).__name__
        error_tb = traceback.format_exc()
        logger.error(
            f"WS ошибка для источника {source_id} [{error_type}]: {error}\n{error_tb}"
        )
        CandleSourceError.objects.create(
            candle_source_id=source_id,
            message=str(error),
            type=error_type,
            traceback=error_tb,
        )
        send_notification.delay(
            message=(
                f"WebSocket ошибка для источника {source_id}\n[{error_type}]: {error}"
            ),
        )
