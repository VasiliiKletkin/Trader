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


class ArbitrageCandleCache:
    """Буферизует и спаривает свечи с двух бирж для арбитражных трейдеров.

    Для каждого трейдера хранит буфер (left/right свечи) и готовую пару.
    При совпадении timestamp left и right — записывает пару.
    """

    BUFFER_PREFIX = "arb:buf"
    PAIRED_PREFIX = "arb:paired"

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

    def _buffer_key(self, trader_id: int, side: str) -> str:
        return f"{self.BUFFER_PREFIX}:{trader_id}:{side}"

    def _paired_key(self, trader_id: int) -> str:
        return f"{self.PAIRED_PREFIX}:{trader_id}"

    async def set_candle(
        self,
        trader_id: int,
        side: str,
        candle: dict,
        ttl: int = 300,
    ) -> bool:
        """Буферизует свечу одной стороны. Возвращает True если пара готова.

        Args:
            trader_id: ID арбитражного трейдера.
            side: "left" или "right".
            candle: Сериализованная свеча (dict с dt_unix).
            ttl: Время жизни буфера (секунды).

        Returns:
            True если обе свечи с совпадающим timestamp готовы.
        """
        buf_key = self._buffer_key(trader_id, side)
        await self._redis.set(buf_key, json.dumps(candle), ex=ttl)

        # Читаем противоположную сторону
        other_side = "right" if side == "left" else "left"
        other_raw = await self._redis.get(
            self._buffer_key(trader_id, other_side),
        )
        if other_raw is None:
            return False

        other_candle = json.loads(other_raw)
        if candle["dt_unix"] != other_candle["dt_unix"]:
            return False

        # Таймстампы совпали — записываем пару
        if side == "left":
            paired = {"left": candle, "right": other_candle}
        else:
            paired = {"left": other_candle, "right": candle}

        paired_key = self._paired_key(trader_id)
        await self._redis.set(paired_key, json.dumps(paired), ex=ttl)

        # Сбрасываем буфер
        await self._redis.delete(
            buf_key,
            self._buffer_key(trader_id, other_side),
        )

        return True

    async def get_paired_candle(self, trader_id: int) -> dict | None:
        """Читает готовую пару свечей из Redis."""
        raw = await self._redis.get(self._paired_key(trader_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def delete_paired_candle(self, trader_id: int) -> None:
        """Удаляет пару после потребления."""
        await self._redis.delete(self._paired_key(trader_id))
