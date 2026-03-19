import json

import redis.asyncio as aioredis


class ArbitrageCandleCache:
    """Буферизует и спаривает свечи с двух бирж для арбитражных трейдеров.

    Для каждого трейдера хранит буфер (left/right свечи) и готовую пару.
    При совпадении timestamp left и right — записывает пару и публикует событие.
    """

    BUFFER_PREFIX = "arb:buf"
    PAIRED_PREFIX = "arb:paired"
    CHANNEL_PREFIX = "arb_candle"

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

        # Pub/Sub для ArbitrageTraderWorker
        channel = f"{self.CHANNEL_PREFIX}:{trader_id}"
        await self._redis.publish(channel, json.dumps(paired))

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
