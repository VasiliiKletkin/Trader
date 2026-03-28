"""
ArbitrageCandleProvider — спаривает свечи с двух бирж для арбитражных трейдеров.

Подписывается на обновления свечей, буферизует left/right стороны,
и при совпадении timestamp записывает готовую пару в Redis + Pub/Sub.
"""

import asyncio
import contextlib
import json
import signal
from collections import defaultdict

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from loguru import logger

from candle_sources.domain.ws.arbitrage_candle_cache import ArbitrageCandleCache


class ArbitrageCandleProvider:
    """Спаривает свечи от двух источников для арбитражных трейдеров.

    Периодически загружает конфигурации ArbitrageTrader из БД,
    строит маппинг (exchange, symbol, timeframe) → [(trader_id, side)].
    Подписан на Redis Pub/Sub `candle:*` — при получении свечи
    буферизует и парит через ArbitrageCandleCache.
    """

    RECONCILE_INTERVAL = 60  # секунд

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        # (exchange_name, symbol, timeframe) → list[(trader_id, "left"|"right")]
        self._subscriptions: dict[tuple[str, str, str], list[tuple[int, str]]] = (
            defaultdict(list)
        )
        # trader_id → timeframe (для расчёта TTL)
        self._trader_timeframes: dict[int, str] = {}

        redis_settings = settings.REDIS
        self._cache = ArbitrageCandleCache(
            host=str(redis_settings["HOST"]),
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=str(redis_settings.get("PASSWORD") or ""),
        )

    async def run(self) -> None:
        logger.info("ArbitrageCandleProvider запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        await self._reconcile()

        reconcile_task = asyncio.create_task(self._reconcile_loop())
        pubsub_task = asyncio.create_task(self._pubsub_loop())

        await self.shutdown_event.wait()

        reconcile_task.cancel()
        pubsub_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(reconcile_task, pubsub_task)

        logger.info("ArbitrageCandleProvider завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения...")
        self.shutdown_event.set()

    # --- Pub/Sub ---

    async def _pubsub_loop(self) -> None:
        redis_settings = settings.REDIS
        redis = aioredis.Redis(
            host=str(redis_settings["HOST"]),
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=str(redis_settings.get("PASSWORD") or ""),
        )
        pubsub = redis.pubsub()
        await pubsub.psubscribe("candle:*")
        logger.info("Подписан на candle:*")

        try:
            while not self.shutdown_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue

                channel = message["channel"].decode()
                parts = channel.split(":")
                if len(parts) != 4:
                    continue

                _, exchange_name, symbol, timeframe = parts
                key = (exchange_name, symbol, timeframe)

                subscriptions = self._subscriptions.get(key)
                if not subscriptions:
                    continue

                candle_data = json.loads(message["data"])

                for trader_id, side in subscriptions:
                    timeframe_str = self._trader_timeframes.get(trader_id, "1h")
                    ttl = self._timeframe_to_seconds(timeframe_str)
                    try:
                        paired = await self._cache.set_candle(
                            trader_id=trader_id,
                            side=side,
                            candle=candle_data,
                            ttl=ttl,
                        )
                        if paired:
                            logger.debug(f"Пара готова для трейдера #{trader_id}")
                    except Exception:
                        logger.exception(f"Ошибка паринга для трейдера #{trader_id}")
        finally:
            await pubsub.punsubscribe("candle:*")
            await pubsub.close()
            await redis.close()

    # --- Reconcile ---

    async def _reconcile_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(self.RECONCILE_INTERVAL)
            await self._reconcile()

    async def _reconcile(self) -> None:
        """Загружает конфигурации ArbitrageTrader из БД."""
        configs = await self._load_trader_configs()

        new_subscriptions: dict[tuple[str, str, str], list[tuple[int, str]]] = (
            defaultdict(list)
        )
        new_timeframes: dict[int, str] = {}

        for cfg in configs:
            new_subscriptions[cfg["left_key"]].append((cfg["trader_id"], "left"))
            new_subscriptions[cfg["right_key"]].append((cfg["trader_id"], "right"))
            new_timeframes[cfg["trader_id"]] = cfg["timeframe"]

        self._subscriptions = new_subscriptions
        self._trader_timeframes = new_timeframes

        logger.info(
            f"Reconcile: {len(new_timeframes)} арбитражных трейдеров, "
            f"{len(new_subscriptions)} подписок"
        )

    @sync_to_async
    def _load_trader_configs(self) -> list[dict]:
        from arbitrage_traders.models import ArbitrageTrader
        from arbitrage_traders.schemas import ArbitrageTraderStatus

        traders = ArbitrageTrader.objects.filter(
            status__in=[
                ArbitrageTraderStatus.ENABLED,
                ArbitrageTraderStatus.PAUSED,
                ArbitrageTraderStatus.ERROR,
            ],
        ).select_related(
            "left_candle_source__exchange_client__exchange",
            "left_candle_source__trading_pair",
            "right_candle_source__exchange_client__exchange",
            "right_candle_source__trading_pair",
        )

        configs = []
        for t in traders:
            left_cs = t.left_candle_source
            right_cs = t.right_candle_source
            configs.append(
                {
                    "trader_id": t.pk,
                    "left_key": (
                        left_cs.exchange_client.exchange.name,
                        left_cs.trading_pair.name,
                        left_cs.timeframe,
                    ),
                    "right_key": (
                        right_cs.exchange_client.exchange.name,
                        right_cs.trading_pair.name,
                        right_cs.timeframe,
                    ),
                    "timeframe": left_cs.timeframe,
                }
            )
        return configs

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        mapping = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
            "1w": 604800,
        }
        return mapping.get(timeframe, 3600)
