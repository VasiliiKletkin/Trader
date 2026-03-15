import json

import redis.asyncio as aioredis


class BalanceRedisCache:
    """Кэширует балансы exchange_client в Redis."""

    KEY_PREFIX = "ws:balance"
    TTL = 300  # 5 минут

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

    async def set_balance(
        self,
        exchange_client_id: int,
        balance: dict,
    ) -> None:
        """Сохраняет баланс в Redis."""
        # Фильтруем только валюты с ненулевым total
        filtered = {
            currency: values
            for currency, values in balance.items()
            if isinstance(values, dict)
            and values.get("total") is not None
            and float(values["total"]) > 0
        }
        if filtered:
            await self._redis.set(
                self._key(exchange_client_id),
                json.dumps(filtered),
                ex=self.TTL,
            )

    async def get_balance(self, exchange_client_id: int) -> dict | None:
        """Читает баланс из Redis."""
        data = await self._redis.get(self._key(exchange_client_id))
        if data is None:
            return None
        return json.loads(data)


class OrdersRedisCache:
    """Кэширует последние ордера exchange_client в Redis."""

    KEY_PREFIX = "ws:orders"
    TTL = 300  # 5 минут

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

    def _key(self, exchange_client_id: int, symbol: str) -> str:
        return f"{self.KEY_PREFIX}:{exchange_client_id}:{symbol}"

    async def set_orders(
        self,
        exchange_client_id: int,
        symbol: str,
        orders: list[dict],
    ) -> None:
        """Сохраняет ордера в Redis."""
        if orders:
            await self._redis.set(
                self._key(exchange_client_id, symbol),
                json.dumps(orders),
                ex=self.TTL,
            )

    async def get_orders(
        self, exchange_client_id: int, symbol: str
    ) -> list[dict] | None:
        """Читает ордера из Redis."""
        data = await self._redis.get(self._key(exchange_client_id, symbol))
        if data is None:
            return None
        return json.loads(data)
