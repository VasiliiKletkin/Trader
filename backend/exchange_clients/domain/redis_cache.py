"""Redis-кэши для WS-стримов балансов и ордеров."""

import json

import redis.asyncio as aioredis

from exchange_clients.domain.schemas import ExchangeClientBalance, ExchangeClientOrder


class BalanceRedisCache:
    """Кэширует последний баланс по exchange_client_id."""

    KEY_PREFIX = "ws:balance"
    TTL = 300

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

    def _key(self, exchange_client_id: int) -> str:
        return f"{self.KEY_PREFIX}:{exchange_client_id}"

    async def set_balances(
        self,
        exchange_client_id: int,
        balances: list[ExchangeClientBalance],
    ) -> None:
        """Сохраняет балансы в Redis."""
        filtered = [b for b in balances if b.total > 0]
        if filtered:
            data = [b.model_dump(mode="json") for b in filtered]
            await self._redis.set(
                self._key(exchange_client_id),
                json.dumps(data),
                ex=self.TTL,
            )

    async def get_balances(
        self, exchange_client_id: int
    ) -> list[ExchangeClientBalance]:
        """Читает балансы из Redis."""
        raw = await self._redis.get(self._key(exchange_client_id))
        if raw is None:
            return []
        return [ExchangeClientBalance(**item) for item in json.loads(raw)]


class OrderRedisCache:
    """Кэширует последние ордера по exchange_client_id."""

    KEY_PREFIX = "ws:orders"
    MAX_ORDERS = 50
    TTL = 300

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

    def _key(self, exchange_client_id: int) -> str:
        return f"{self.KEY_PREFIX}:{exchange_client_id}"

    async def add_orders(
        self,
        exchange_client_id: int,
        orders: list[ExchangeClientOrder],
    ) -> None:
        """Добавляет ордера в Redis (FIFO, макс MAX_ORDERS)."""
        key = self._key(exchange_client_id)
        pipe = self._redis.pipeline()
        for order in orders:
            pipe.rpush(key, json.dumps(order.model_dump(mode="json")))
        pipe.ltrim(key, -self.MAX_ORDERS, -1)
        pipe.expire(key, self.TTL)
        await pipe.execute()

    async def get_orders(self, exchange_client_id: int) -> list[ExchangeClientOrder]:
        """Читает ордера из Redis."""
        raw_list = await self._redis.lrange(
            self._key(exchange_client_id),
            0,
            -1,
        )
        return [ExchangeClientOrder(**json.loads(raw)) for raw in raw_list]
