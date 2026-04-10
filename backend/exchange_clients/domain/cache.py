"""Redis-кэш для WS-стримов exchange client'ов."""

import redis.asyncio as aioredis
from pydantic import TypeAdapter

from exchange_clients.domain.schemas import ExchangeClientBalance, ExchangeClientOrder

BALANCE_KEY_PREFIX = "ws:balance"
ORDERS_KEY_PREFIX = "ws:orders"
DEFAULT_TTL = 300
MAX_ORDERS = 50

_balance_adapter = TypeAdapter(ExchangeClientBalance)
_order_adapter = TypeAdapter(ExchangeClientOrder)


class ExchangeCache:
    """Кэширует балансы и ордера по exchange_client_id."""

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

    # --- Балансы ---

    async def set_balances(
        self,
        exchange_client_id: int,
        market_type: str,
        balances: list[ExchangeClientBalance],
    ) -> None:
        """Сохраняет балансы в Redis Hash (currency → json)."""
        key = f"{BALANCE_KEY_PREFIX}:{exchange_client_id}:{market_type}"
        mapping = {
            b.currency: b.model_dump_json().encode() for b in balances if b.total > 0
        }
        if mapping:
            await self._redis.hset(key, mapping=mapping)  # type: ignore[arg-type]
            await self._redis.expire(key, DEFAULT_TTL)

    async def get_balances(
        self,
        exchange_client_id: int,
        market_type: str,
        currency: str | None = None,
    ) -> list[ExchangeClientBalance]:
        """Читает балансы из Redis Hash. Если currency — только одну валюту."""
        key = f"{BALANCE_KEY_PREFIX}:{exchange_client_id}:{market_type}"
        if currency is not None:
            raw = await self._redis.hget(key, currency)
            if raw is None:
                return []
            return [_balance_adapter.validate_json(raw)]
        raw_all = await self._redis.hgetall(key)
        return [_balance_adapter.validate_json(v) for v in raw_all.values()]

    # --- Ордера ---

    async def add_orders(
        self,
        exchange_client_id: int,
        orders: list[ExchangeClientOrder],
    ) -> None:
        """Добавляет ордера в Redis (FIFO, макс MAX_ORDERS)."""
        key = f"{ORDERS_KEY_PREFIX}:{exchange_client_id}"
        pipe = self._redis.pipeline()
        for order in orders:
            pipe.rpush(key, order.model_dump_json())
        pipe.ltrim(key, -MAX_ORDERS, -1)
        pipe.expire(key, DEFAULT_TTL)
        await pipe.execute()

    async def get_orders(
        self,
        exchange_client_id: int,
    ) -> list[ExchangeClientOrder]:
        """Читает ордера из Redis."""
        raw_list = await self._redis.lrange(
            f"{ORDERS_KEY_PREFIX}:{exchange_client_id}",
            0,
            -1,
        )
        return [_order_adapter.validate_json(raw) for raw in raw_list]
