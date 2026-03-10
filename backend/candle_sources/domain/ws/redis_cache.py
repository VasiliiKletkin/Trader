import json

import redis.asyncio as aioredis

from exchanges.domain import Candle, Exchange, Timeframe, TradingPair


class CandleRedisCache:
    """Кэширует последние 2 свечи в Redis (предыдущая + формирующаяся)."""

    KEY_PREFIX = "ws:candle"
    MAX_CANDLES = 2

    def __init__(
        self,
        host: str = "redis",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ):
        self._redis = aioredis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
        )

    def _key(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> str:
        return (
            f"{self.KEY_PREFIX}:{exchange.name}:{trading_pair.symbol}:{timeframe.value}"
        )

    async def set_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        candle: Candle,
    ) -> None:
        """Сохраняет свечу в Redis, поддерживая словарь из последних 2 свечей.

        Ключ словаря — dt_unix (timestamp).
        Если свеча с таким timestamp уже есть — обновляет.
        Если новый timestamp — добавляет и удаляет самую старую.
        """
        key = self._key(exchange, trading_pair, timeframe)
        ttl = int(timeframe.timedelta().total_seconds())
        ts = str(candle.dt_unix)

        raw = await self._redis.get(key)
        candles: dict[str, dict] = json.loads(raw) if raw else {}

        candles[ts] = candle.model_dump(mode="json")

        if len(candles) > self.MAX_CANDLES:
            oldest_key = min(candles)
            del candles[oldest_key]

        await self._redis.set(key, json.dumps(candles), ex=ttl)

    async def get_candles(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> dict[int, Candle]:
        """Читает последние свечи из Redis. Ключ — dt_unix."""
        data = await self._redis.get(
            self._key(exchange, trading_pair, timeframe),
        )
        if data is None:
            return {}
        return {
            int(ts): Candle.model_validate(item)
            for ts, item in json.loads(data).items()
        }

    async def delete_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> None:
        """Удаляет свечи из кэша."""
        await self._redis.delete(
            self._key(exchange, trading_pair, timeframe),
        )
