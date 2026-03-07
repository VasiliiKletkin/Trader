import asyncio
import traceback
from datetime import UTC, datetime

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from loguru import logger

from candle_sources.domain.ws.manager import WebSocketStreamManager
from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.domain.ws.schemas import SubscriptionConfig
from exchanges.domain import Exchange, Timeframe, TradingPair


class Command(BaseCommand):
    help = "Запускает WebSocket стримы для получения OHLCV свечей"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        redis_settings = settings.REDIS
        self.redis_cache = CandleRedisCache(
            host=redis_settings["HOST"],
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["DATABASE"]),
            password=redis_settings.get("PASSWORD") or None,
        )

    def handle(self, *args, **options):
        self.stdout.write("Запуск WebSocket стримов...")
        manager = WebSocketStreamManager(
            load_subscriptions=self._load_subscriptions_async,
            on_candle=self._on_candle,
            on_error=self._on_error,
            sync_interval=30,
        )
        asyncio.run(manager.run())

    async def _load_subscriptions_async(self) -> list[SubscriptionConfig]:
        return await sync_to_async(self._load_subscriptions)()

    def _load_subscriptions(self) -> list[SubscriptionConfig]:
        from candle_sources.models import CandleSource, CandleSourceMode

        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "exchange_client__proxy",
            "trading_pair",
        )

        return [
            SubscriptionConfig(
                source_id=source.pk,
                exchange=source.exchange_client.exchange.instantiate(),
                trading_pair=source.trading_pair.instantiate(),
                timeframe=Timeframe(source.timeframe),
                exchange_client=source.exchange_client.instantiate(),
            )
            for source in sources
        ]

    async def _on_candle(
        self,
        source_id: int,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        ohlcv: list,
    ) -> None:
        try:
            await self.redis_cache.set_candle(
                exchange=exchange,
                trading_pair=trading_pair,
                timeframe=timeframe,
                ohlcv=ohlcv,
            )

            timestamp_ms, open_, high, low, close, volume = ohlcv
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
            await self._upsert_candle(
                source_id, timestamp, open_, high, low, close, volume
            )
            await self._trigger_traders(source_id)
        except Exception as e:
            await self._on_error(source_id, e)

    @sync_to_async
    def _upsert_candle(
        self,
        source_id: int,
        timestamp: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        from candle_sources.models import CandleSource
        from exchanges.models import ExchangeCandle

        source = CandleSource.objects.select_related(
            "exchange_client__exchange", "trading_pair"
        ).get(pk=source_id)

        ExchangeCandle.objects.bulk_create(
            [
                ExchangeCandle(
                    exchange=source.exchange_client.exchange,
                    timeframe=source.timeframe,
                    trading_pair=source.trading_pair,
                    timestamp=timestamp,
                    open=open,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            ],
            batch_size=settings.BULK_BATCH_SIZE,
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
        )

        source.last_synced = timezone.now()
        source.save(update_fields=["last_synced"])

    @sync_to_async
    def _trigger_traders(self, source_id: int) -> None:
        from candle_sources.models import CandleSource
        from candle_sources.tasks import (
            arbitrage_traders_process_by_sources,
            traders_process_by_sources,
        )

        candle_sources = list(CandleSource.objects.filter(pk=source_id))
        traders_process_by_sources(candle_sources=candle_sources)
        arbitrage_traders_process_by_sources(candle_sources=candle_sources)

    async def _on_error(self, source_id: int, error: Exception) -> None:
        logger.error(
            f"WS ошибка для источника {source_id} "
            f"[{type(error).__name__}]: {error}\n"
            f"{traceback.format_exc()}"
        )
