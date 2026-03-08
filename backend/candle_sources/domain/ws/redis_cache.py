import redis.asyncio as aioredis

from exchanges.domain import Candle, Exchange, Timeframe, TradingPair


class CandleRedisCache:
    """Кэширует текущую формирующуюся свечу в Redis."""

    KEY_PREFIX = "ws:candle"

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
        """Сохраняет свечу в Redis по ключу ws:candle:{exchange}:{symbol}:{timeframe}."""
        ttl = int(timeframe.timedelta().total_seconds())
        await self._redis.set(
            self._key(exchange, trading_pair, timeframe),
            candle.model_dump_json(),
            ex=ttl,
        )

    async def get_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> Candle | None:
        """Читает последнюю свечу из Redis."""
        data = await self._redis.get(self._key(exchange, trading_pair, timeframe))
        if data is None:
            return None
        return Candle.model_validate_json(data)

    async def delete_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> None:
        """Удаляет свечу из кэша."""
        await self._redis.delete(self._key(exchange, trading_pair, timeframe))
