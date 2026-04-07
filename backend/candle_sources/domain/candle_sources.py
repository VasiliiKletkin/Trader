import asyncio
import traceback
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from pydantic import BaseModel

from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain import Candle, Timeframe, TradingPair


class CandleSourceError(BaseModel):
    """Ошибка при получении свечей."""

    message: str
    type: str
    traceback: str | None = None


class CandleSource:
    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        source_id: int | None = None,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.source_id = source_id
        self.errors: list[CandleSourceError] = []

    async def _fetch_candles_batch(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Один запрос к API биржи."""
        try:
            return await self.exchange_client.fetch_candles(
                trading_pair=self.trading_pair,
                timeframe=self.timeframe,
                since=since,
                limit=limit,
            )
        except Exception as e:
            self.errors.append(
                CandleSourceError(
                    message=getattr(e, "error_message", None) or str(e),
                    type=getattr(e, "error_type", None) or type(e).__name__,
                    traceback=getattr(e, "error_traceback", None)
                    or traceback.format_exc(),
                )
            )
            return []

    def _build_batch_params(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[tuple[datetime | None, int]]:
        """Вычисляет параметры (since, limit) для каждого батча."""
        now = datetime.now(tz=UTC)
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")

        max_per_req = self.exchange_client.exchange.max_candles_per_request
        step_delta = self.timeframe.timedelta() * max_per_req

        total_steps = 1
        if since:
            total_steps = ((now - since) // step_delta) + 1
        if limit:
            total_steps = min(total_steps, (limit // max_per_req) + 1)

        params: list[tuple[datetime | None, int]] = []
        for i in range(total_steps):
            batch_limit = max_per_req
            if limit:
                batch_limit = min(max_per_req, limit - i * max_per_req)
                if batch_limit <= 0:
                    break
            batch_since = since + i * step_delta if since else None
            params.append((batch_since, batch_limit))
        return params

    async def fetch_candles(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Скачивает все свечи параллельно."""
        params = self._build_batch_params(since=since, limit=limit)
        results = await asyncio.gather(
            *[self._fetch_candles_batch(since=s, limit=lim) for s, lim in params]
        )
        seen: dict[datetime, Candle] = {}
        for batch in results:
            for c in batch:
                seen[c.timestamp] = c
        return list(seen.values())

    async def fetch_candles_iter(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[list[Candle]]:
        """Итератор: отдаёт свечи батчами, последовательно."""
        for s, lim in self._build_batch_params(since=since, limit=limit):
            candles = await self._fetch_candles_batch(since=s, limit=lim)
            if not candles:
                break
            yield candles
